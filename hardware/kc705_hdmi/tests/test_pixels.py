#!/usr/bin/env python3
"""MMIO protocol, double buffering and RGB565 pixels on the actual HDMI bus."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from test import ROOT, REPO, run, decoded_rgb


def color565(value):
    r, g, b = value >> 11, (value >> 5) & 63, value & 31
    r, g, b = (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)
    return (((66*r+129*g+25*b+128)//256)+16,
            ((-38*r-74*g+112*b+128)//256)+128,
            ((112*r-94*g-18*b+128)//256)+128)


def verify(out, expected, width=160, height=120, video_720p=False):
    """Infer frame origins from external sync; no DUT counter supplies pixels."""
    aw,ah,ht,vt,hs,he,vs,ve=(1280,720,1650,750,1390,1430,725,730) if video_720p else (640,480,800,525,656,752,490,492)
    assert width*ah==height*aw
    period=ht*vt
    raw = (out/'hdmi-stream.bin').read_bytes()
    assert len(raw) % 4 == 0
    flags, tags = raw[2::4], raw[3::4]
    falls = [i for i in range(1, len(flags)) if (bool(flags[i-1]&4),bool(flags[i]&4)) == ((False,True) if video_720p else (True,False))]
    assert len(falls) >= 3
    assert all(b-a == period for a,b in zip(falls,falls[1:]))
    checked, seen = 0, set()
    for fall in falls:
        origin = fall+(vt-vs)*ht
        if origin+period > len(flags) or not flags[origin]&8:
            continue
        tag, bank = tags[origin], flags[origin]&16
        frame = expected(tag)
        rgb = bytearray()
        for y in range(vt):
            row = origin+y*ht
            for x in range(ht):
                f = flags[row+x]
                assert bool(f&1) == (x<aw and y<ah), ('DE',x,y)
                assert bool(f&2) == ((hs<=x<he) == video_720p), ('HS',x,y)
                assert bool(f&4) == ((vs<=y<ve) == video_720p), ('VS',x,y)
                if x<aw and y<ah:
                    assert flags[row+x]&16 == bank and tags[row+x] == tag, 'Torn frame'
            if y >= ah:
                continue
            for x in range(0,aw,2):
                a = color565(int(frame[(y*height//ah)*width+x*width//aw]))
                b = color565(int(frame[(y*height//ah)*width+(x+1)*width//aw]))
                cb, cr = (a[1]+b[1]+1)//2, (a[2]+b[2]+1)//2
                p = (row+x)*4
                even, odd = raw[p]|raw[p+1]<<8, raw[p+4]|raw[p+5]<<8
                assert (even,odd) == ((cb<<8)|a[0],(cr<<8)|b[0]), (tag,x,y,'pixel')
                rgb.extend(decoded_rgb(even&255,even>>8,odd>>8))
                rgb.extend(decoded_rgb(odd&255,even>>8,odd>>8))
                checked += 2
        if tag not in seen:
            (out/f'frame-{tag}.ppm').write_bytes(f'P6\n{aw} {ah}\n255\n'.encode()+rgb)
        seen.add(tag)
    assert checked > 0
    return {'hdmi_pixels_checked': checked, 'captured_tags': sorted(seen), 'display':[aw,ah], 'render_resolution':[width,height]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--video-mode',choices=('vga','720p'),default='vga')
    parser.add_argument('--synth',action='store_true',help='Also exercise Yosys DSP/coarse synthesis output')
    args=parser.parse_args();hd=args.video_mode=='720p'
    if args.synth and any(shutil.which(tool) is None for tool in ('yosys','yosys-config')):
        print('SKIP: coarse synthesis regression requires yosys and yosys-config')
        raise SystemExit(77)
    width,height=(480,270) if hd else (160,120)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT/'src/kc705_hdmi_pixels.sv', Path(__file__).with_name('tb_pixels.sv')]
    inputs={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sources,Path(__file__)]}
    compile_sources=sources
    defines=[]
    if args.synth:
        script=out/'synth.ys';netlist=out/'pixels.v'
        script.write_text(f'read_verilog -sv "{sources[0]}"\n'
            f'chparam -set WIDTH {width} -set HEIGHT {height} -set VIDEO_720P {int(hd)} kc705_hdmi_pixels\n'
            'synth_xilinx -family xc7 -top kc705_hdmi_pixels -noiopad -noclkbuf -run begin:coarse\n'
            'memory_collect\nopt_clean\ncheck -assert\n'+f'write_verilog -noattr "{netlist}"\n')
        run(['yosys','-Q','-T','-s',str(script)],out/'synth.log',REPO)
        # Use the unelaborated behavioral DSP model so parameters remain intact.
        # Memory is still inferred RTL at this stage.
        model=out/'dsp.v'
        datdir=Path(subprocess.check_output(['yosys-config','--datdir'],text=True).strip())
        model.write_text(re.search(r'module DSP48E1\b.*?\nendmodule',(datdir/'xilinx/cells_sim.v').read_text(),re.S)[0]+'\n')
        compile_sources=[netlist,model,sources[1]];defines=['-DSYNTHESIZED']
    run(['verilator','--binary','--timing','-Wno-fatal','--top-module','tb_pixels',
         *defines,
         f'-GVIDEO_720P={int(hd)}',f'-GWIDTH={width}',f'-GHEIGHT={height}',
         '--Mdir',str(out/'obj'),'-o',str(out/'sim'),'-j','4',*map(str,compile_sources)],out/'compile.log',REPO)
    log = run([str(out/'sim'),'+OUT_DIR='+str(out)],out/'simulation.log',REPO)
    assert 'PIXELS_PASS' in log
    def expected(tag):
        return [(((x+tag*7)%32)<<11)|(((y+tag*11)%64)<<5)|((x+y+tag*13)%32)
                for y in range(height) for x in range(width)]
    report = verify(out, expected,width,height,hd)
    assert report['captured_tags'] == [0,1,2], report
    for path,digest in inputs.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Source changed during verification: '+path)
    report.update(passed=True,coarse_synthesis=args.synth,scope='MMIO and digital HDMI RTL; no CPU, physical board or DDR3 claim',
                  checks=['ordered complete frames','invalid/partial/unaligned/out-of-range accesses',
                          'response backpressure','immutable pending frame','vblank swaps',
                          'concurrent back writes and front scanout','reset invalidates partial upload'],
                  sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sources,*compile_sources,Path(__file__)]})
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
