#!/usr/bin/env python3
"""Verify actual TPU rendering and the emitted HDMI bus against scalar oracles."""
from __future__ import annotations
import argparse
from bisect import bisect_right
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
CHROMATIC = ROOT.parent/'chromatic'
sys.path.insert(0, str(ROOT/'tools'))
from reference import reference
CPU_MESH=json.loads((ROOT/'assets/mesh.json').read_text())

WIDTH, HEIGHT, HTOTAL, VTOTAL = 640, 480, 800, 525
PERIOD = HTOTAL*VTOTAL
BARS = [(63,63,63),(63,63,0),(0,63,63),(0,63,0),
        (63,0,63),(63,0,0),(0,0,63),(0,0,0)]
# Fixed BT.601 bar vectors in KC705 board-pin order. ADI's reference
# ad_ss_444to422 emits {Cb,Y}/{Cr,Y}; axi_hdmi_tx_core and KC705 system_top
# preserve that order through system_constr.xdc. These literals deliberately
# do not derive the bus mapping from either DUT packing or the ycc() oracle.
BAR_WORDS = [(0x80eb,0x80eb),(0x10d2,0x92d2),(0xa6a9,0x10a9),(0x3690,0x2290),
             (0xca6b,0xde6b),(0x5a52,0xf052),(0xf029,0x6e29),(0x8010,0x8010)]
FONT = {int(code):int(bits,2) for code,bits in re.findall(
    r"8'd(\d+):glyph=15'b([01]{15})", (CHROMATIC/'src/font.vh').read_text())}


def require(ok, message):
    if not ok: raise AssertionError(message)


@lru_cache(maxsize=None)
def palette(x, y, pixel, phase, cycles, cpu=False):
    """Independent native-resolution layout and gold material palette."""
    gold = [(24,12,1)]*4+[(30,16,1),(36,21,1),(42,27,2),(46,33,2),
            (50,39,3),(54,43,4),(57,47,6),(59,50,9),(61,53,12),
            (62,56,16),(63,59,22),(63,61,29)]
    if cpu:
        a,b=gold[min(pixel//4,15)],gold[min(pixel//4+1,15)]
        material=tuple((x*(4-pixel%4)+y*(pixel%4)+2)//4 for x,y in zip(a,b))
    else:material=gold[pixel]
    color = material if pixel else (3+(y//128),4+(y//128),7+(y//64))
    if y in (65,420) and 32<=x<608: color=(12,15,20)
    labels=[(32,28,3,'TINY3TPU',True),(520,33,2,'JAX CPU TPU' if cpu else 'REALTIME 3D',False),
            (32,435,2,f"{len(CPU_MESH['faces'])} TRIANGLES" if cpu else '407 TRIANGLES',False),(224,435,2,f"{len(CPU_MESH['vertices'])} VERTICES" if cpu else '204 VERTICES',False),
            (552,435,2,'ON FPGA',False),(32,454,2,'2X4X4 TPU' if cpu else '4X4 TPU',False),
            (224,454,2,'640X480 RENDER',False),(536,454,2,'60HZ HDMI',False)]
    for ox,oy,scale,text,title in labels:
        if ox<=x<ox+len(text)*4*scale and oy<=y<oy+5*scale:
            col,gx=(x-ox)//(4*scale),((x-ox)//scale)%4
            gy=(y-oy)//scale
            if gx<3 and (FONT.get(ord(text[col]),0)>>(14-gy*3-gx))&1:
                color=(63,57,26) if title else (39,43,49)
    return color


@lru_cache(maxsize=None)
def ycc(rgb6):
    r,g,b = ((c<<2)|(c>>4) for c in rgb6)
    return (((66*r+129*g+25*b+128)//256)+16,
            ((-38*r-74*g+112*b+128)//256)+128,
            ((112*r-94*g-18*b+128)//256)+128)


def decoded_rgb(y, cb, cr):
    # Standard limited-range BT.601 inverse. The capture is intentionally
    # reconstructed from actual paired HDMI samples, not the RGB oracle.
    c,d,e = y-16,cb-128,cr-128
    return bytes(max(0,min(255,value)) for value in (
        (298*c+409*e+128)//256,
        (298*c-100*d-208*e+128)//256,
        (298*c+516*d+128)//256))


def run(command, log, cwd):
    with log.open('w') as stream:
        completed = subprocess.run(command, cwd=cwd, stdout=stream,
                                   stderr=subprocess.STDOUT, timeout=240)
    if completed.returncode: raise RuntimeError(log.read_text()[-16000:])
    return log.read_text()


def verify_capture(out, images, log):
    raw = (out/'hdmi-stream.bin').read_bytes()
    require(len(raw)%3 == 0, 'Truncated HDMI capture')
    samples = len(raw)//3
    flags = raw[2::3]
    # Synchronization is inferred solely from external HS/VS, not DUT counters.
    vs_falls = [i for i in range(1,samples) if flags[i-1]&4 and not flags[i]&4]
    hs_falls = [i for i in range(1,samples) if flags[i-1]&2 and not flags[i]&2]
    require(len(vs_falls)>=9, 'Not enough complete vertical scans')
    require(all(b-a == PERIOD for a,b in zip(vs_falls,vs_falls[1:])), 'VS period is not 800x525')
    require(all(b-a == HTOTAL for a,b in zip(hs_falls,hs_falls[1:])), 'HS period is not 800 clocks')
    ticks = [i for i,flag in enumerate(flags) if flag&128]
    require(len(ticks)>=9 and all(b-a == PERIOD for a,b in zip(ticks,ticks[1:])), 'frame_tick is not one clock per frame')
    states = [list(map(int,line.split())) for line in (out/'states.txt').read_text().splitlines()]
    starts = [state[0] for state in states]
    renders = {int(p):{'cycles':int(c)-1,'coordinates':int(n),'pixels':int(px),'gemms':int(g)}
               for p,c,n,px,g in re.findall(r'RENDER phase=(\d+) cycles=(\d+) coordinates=(\d+) pixels=(\d+) gemms=(\d+)',log)}
    counts = re.search(r'HDMI_RTL_PASS coordinates=(\d+) pixels=(\d+) gemms=(\d+) renders=(\d+) publications=(\d+) concurrent_writes=(\d+) samples=(\d+)',log)
    require(counts is not None, 'RTL assertions did not finish')
    inflight = re.search(r'HDMI_INCLUDING_INFLIGHT coordinates=(\d+) launches=(\d+)',log)
    require(inflight is not None, 'Missing accelerator coverage totals')
    # Startup must remain disabled despite an enable request during active scan.
    first_origin = vs_falls[0]+(VTOTAL-490)*HTOTAL
    require(not any(flag&1 for flag in flags[:first_origin]), 'Startup enabled video before a complete frame boundary')
    report_frames, checked_pixels, checked_timing, chroma_mixed_pairs = [],0,0,0
    render_captures, pattern_captures, disabled_frames = 0,0,0
    for vf in vs_falls:
        origin = vf+(VTOTAL-490)*HTOTAL
        if origin+PERIOD > samples: continue
        # frame_tick refers to the logical (0,480) counter position, before
        # the synchronous read and paired output pipeline. This is three
        # observed sample clocks before that position reaches the output bus.
        require(origin+480*HTOTAL-3 in ticks, 'frame_tick is not at logical (0,480)')
        # Stimuli change in the middle of active scans. They are stable long
        # before the synchronizers sample the preceding frame boundary.
        enabled, pattern = bool(flags[origin-8]&32), bool(flags[origin-8]&64)
        _, valid, bank, phase, visible_cycles, publication = states[bisect_right(starts,origin)-1]
        require(valid and phase in renders, f'Frame {origin}: no completed render')
        require(visible_cycles == renders[phase]['cycles'],
                f'Visible cycle metadata belongs to another frame: phase={phase} {visible_cycles} != {renders[phase]["cycles"]}')
        actual_rgb = bytearray()
        for yy in range(VTOTAL):
            row = origin+yy*HTOTAL
            for xx in range(HTOTAL):
                f = flags[row+xx]
                expected_de = enabled and xx<WIDTH and yy<HEIGHT
                require(bool(f&1) == expected_de, f'DE alignment at frame={origin}, x={xx}, y={yy}')
                require(bool(f&2) == (not 656<=xx<752), f'HS pulse/alignment x={xx}, y={yy}')
                require(bool(f&4) == (not 490<=yy<492), f'VS pulse/alignment x={xx}, y={yy}')
                if yy<HEIGHT and xx<WIDTH:
                    require(bool(f&8) == bool(valid) and bool(f&16) == bool(bank),
                            f'Publication tore active frame x={xx}, y={yy}')
                checked_timing += 1
            if yy>=HEIGHT or not enabled: continue
            expected_row = []
            for xx in range(WIDTH):
                if pattern: rgb = BARS[xx//80]
                else:
                    sx,sy = xx,yy
                    rgb = palette(xx,yy,images[phase][sy*640+sx],phase,visible_cycles)
                expected_row.append(ycc(rgb))
            for xx in range(0,WIDTH,2):
                a,b = expected_row[xx:xx+2]
                cb,cr = (a[1]+b[1]+1)//2,(a[2]+b[2]+1)//2
                even = (raw[(row+xx)*3+1]<<8)|raw[(row+xx)*3]
                odd = (raw[(row+xx+1)*3+1]<<8)|raw[(row+xx+1)*3]
                if pattern:
                    require((even,odd) == BAR_WORDS[xx//80],
                            f'KC705 board-pin color-bar vector mismatch: bar={xx//80} {even:04x}/{odd:04x}')
                require(even == ((cb<<8)|a[0]) and odd == ((cr<<8)|b[0]),
                        f'HDMI pixel/pair mismatch phase={phase}, bars={pattern}, x={xx}, y={yy}: {even:04x}/{odd:04x} expected {(cb<<8)|a[0]:04x}/{(cr<<8)|b[0]:04x}')
                chroma_mixed_pairs += a[1:] != b[1:]
                actual_rgb.extend(decoded_rgb(even&255,even>>8,odd>>8))
                actual_rgb.extend(decoded_rgb(odd&255,even>>8,odd>>8))
                checked_pixels += 2
        if not enabled: disabled_frames += 1
        elif pattern: pattern_captures += 1
        else: render_captures += 1
        capture = None
        if enabled:
            name = f'hdmi-bars-phase{phase:03d}' if pattern else f'hdmi-banana-phase{phase:03d}'
            capture = out/(name+'.ppm')
            capture.write_bytes(b'P6\n640 480\n255\n'+actual_rgb)
            try:
                from PIL import Image
                Image.frombytes('RGB',(WIDTH,HEIGHT),bytes(actual_rgb)).save(out/(name+'.png'))
            except ImportError: pass
        report_frames.append(dict(phase=phase,bank=bank,publication=publication,
                                  cycles=visible_cycles,enabled=enabled,test_pattern=pattern,
                                  capture=str(capture) if capture else None))
    require(render_captures>=4 and pattern_captures>=2 and disabled_frames>=1,
            f'Insufficient mode coverage: rendered={render_captures} bars={pattern_captures} disabled={disabled_frames}')
    require(chroma_mixed_pairs>0, 'No unlike-pixel chroma averaging coverage')
    return dict(scope='RTL simulation of actual TPU, renderer, framebuffer, palette and HDMI parallel bus. No ADV7511, cable, monitor, or physical-board observation.',
                pixel_clock_hz=25200000,refresh_hz=25200000/PERIOD,
                clock_scope='Nominal board rate; this cycle-accurate harness uses a 10 ns clock and does not verify the board clock generator or physical timing.',
                geometry={'active':[WIDTH,HEIGHT],'total':[HTOTAL,VTOTAL],'image':[640,480],'image_origin':[0,0],'render':[640,480]},
                samples=samples,external_timing_samples_checked=checked_timing,
                hdmi_pixels_checked=checked_pixels,mixed_chroma_pairs_checked=chroma_mixed_pairs,
                board_bus_format='HDMI_D[15:8]=Cb/Cr; HDMI_D[7:0]=Y; first active pixel Cb',
                fixed_color_bar_vectors_checked=True,
                rtl_counts=dict(zip(('coordinates','pixels','gemms','renders','publications','concurrent_writes','samples'),map(int,counts.groups()))),
                including_inflight=dict(zip(('coordinates_checked','accelerator_launches'),map(int,inflight.groups()))),
                reset_during_render=True,midframe_enable_pattern_changes=True,
                frames=report_frames,renderer_frames=renders)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/simulation')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    images={}
    with (out/'expected-results.hex').open('w') as qfile,(out/'expected-pixels.hex').open('w') as pfile:
        for phase in range(16):
            coordinates,pixels=reference(phase);images[phase]=pixels
            qfile.write(''.join(f'{v&0xffffffff:08x}\n' for row in coordinates for v in row))
            pfile.write(''.join(f'{v:x}\n' for v in pixels))
    sources=[ROOT/'src/kc705_hdmi_cpu_scene.sv',ROOT/'src/kc705_hdmi_display.sv',ROOT/'src/kc705_hdmi_framebuffer.sv',
             ROOT/'src/kc705_hdmi_renderer.sv',ROOT/'src/kc705_hdmi_ram.sv',ROOT/'src/kc705_hdmi_palette.sv',
             *(CHROMATIC/'src'/name for name in
             ('scene.sv',)),
             REPO/'multi-core/tpu_core_wrapper.sv',REPO/'systolic_array/rtl/NxN_systolic_array.v',
             REPO/'systolic_array/rtl/pe.v',Path(__file__).with_name('tb_display.sv')]
    verilator=shutil.which('verilator')
    if verilator is None: raise RuntimeError('verilator is required')
    run([verilator,'-I'+str(ROOT/'assets'),'--binary','--timing','--top-module','tb_display',
         str(CHROMATIC/'verilator.vlt'),'-Wno-TIMESCALEMOD',
         '-I'+str(CHROMATIC/'src'),'--Mdir',str(out/'obj_display'),'-o',str(out/'simulate-display'),
         '-j','4',*(str(path) for path in sources)],out/'compile.log',CHROMATIC)
    log=run([str(out/'simulate-display'),'+OUT_DIR='+str(out)],out/'simulation.log',CHROMATIC)
    report=verify_capture(out,images,log)
    report['sha256']={str(path.relative_to(REPO)):hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in [*sources,Path(__file__),ROOT/'assets/mesh_config.vh',ROOT/'tools/reference.py',
                                   CHROMATIC/'tools/assets.py',CHROMATIC/'src/font.vh',
                                   *(CHROMATIC/'assets'/name for name in ('mesh.json','vertices.hex','rotations.hex','faces.hex'))]}
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('sha256','frames','renderer_frames')},indent=2))
    print(f'HDMI DISPLAY PASS; captures and evidence: {out}')


if __name__=='__main__':main()
