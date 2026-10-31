"""Actual RV32 MJX/TPU learning, MuJoCo rendering, framebuffer, HDMI."""
from pathlib import Path
import hashlib,json,re,subprocess,sys
import numpy as np
from build import ROOT,native
from export_scene import scene_at
from verify_native import rgb565
HDMI=ROOT/'hardware/kc705_hdmi'
sys.path[:0]=[str(HDMI/'tests'),str(ROOT),str(ROOT/'tests')]
from test import run
from test_pixels import verify as verify_pixels


def check(out,firmware=None,video_mode='vga'):
    out.mkdir(parents=True,exist_ok=True)
    fw=firmware or out/'firmware'
    if firmware is None:
        subprocess.run([sys.executable,str(ROOT/'sidequests/mjx_rl/prepare.py'),'--out',str(fw),
            '--horizon','6','--directions','1','--verify-ticks','16','--video-mode',video_mode],check=True)
    manifest=json.loads((fw/'build-manifest.json').read_text())
    width,height=manifest['framebuffer'];hd=manifest['display']==[1280,720]
    assert manifest['verify_ticks']==16 and manifest['horizon']==6 and manifest['directions']==1
    symbols={p[2]:int(p[0],16) for line in subprocess.check_output(['riscv64-unknown-elf-nm',str(fw/'firmware.elf')],text=True).splitlines() if len(p:=line.split())==3}
    uart=ROOT.parent/'synapse32'
    sources=[HDMI/'src/kc705_hdmi_pixel_system.sv',HDMI/'src/kc705_hdmi_pixels.sv',
        ROOT/'hardware/kc705_vexriscv/vexriscv_tpu_soc.sv',ROOT/'third_party/vexriscv/VexRiscv_Lite.v',
        uart/'rtl/core_modules/uart.v',
        *(ROOT/'multi-core'/n for n in ('tiny3tpu_direct_peripheral.sv','tiny3tpu_axi.sv','top.v','tpu_core_wrapper.sv')),
        ROOT/'systolic_array/rtl/NxN_systolic_array.v',ROOT/'systolic_array/rtl/pe.v',Path(__file__).with_name('tb_mujoco_cpu.sv')]
    hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [*sources,fw/'firmware.elf',fw/'firmware.hex']}
    run(['verilator','--binary','--timing','-Wno-fatal','--top-module','tb_mujoco_cpu',
        '-I'+str(uart/'rtl/include'),f'-GBOOT_HEX="{fw}/firmware.hex"',f'-GRENDER_PC={symbols["mjr_render"]}',
        f'-GVIDEO_720P={int(hd)}',f'-GWIDTH={width}',f'-GHEIGHT={height}',f'-GBOOT_WORDS={manifest["memory"]["ram_bytes"]//4}',
        '--Mdir',str(out/'obj'),'-o',str(out/'sim'),'-j','4',*map(str,sources)],out/'compile.log',ROOT)
    log=run([str(out/'sim'),'+OUT_DIR='+str(out)],out/'simulation.log',ROOT)
    counts=re.search(r'MUJOCO_CPU_PASS cycles=(\d+) core0=(\d+) core1=(\d+) writes=(\d+) submits=(\d+) renderer=(\d+)',log)
    assert counts,log[-2000:]
    states=np.load(fw/'native-states.npy');initial=np.load(fw/'initial.npy')
    assert states[-1,3]==1 and np.any(states[-1,:2]!=0)
    exe=native(out/'native')
    frames=[];comparisons=[]
    for tag in range(3):
        state=initial if tag==0 else states[tag*8-1]
        m,d,scene=scene_at(float(state[6]))
        np.concatenate((d.geom_xpos,d.geom_xmat),axis=1).astype(np.float32).tofile(out/'native/pose.bin')
        want=subprocess.run([str(exe),str(out/'native/pose.bin'),str(width),str(height)],check=True,capture_output=True).stdout
        expected=np.frombuffer(want,np.uint16).reshape(height,width)
        got=np.fromfile(out/f'upload-{tag}.rgb565',np.uint16).reshape(height,width)
        # RISC-V soft-float libm and host libm can differ at triangle boundaries.
        delta=np.abs(rgb565(got).astype(float)-rgb565(expected))
        mismatch=float(np.mean(got!=expected));mae=float(delta.mean())
        assert mismatch<.01 and mae<.3,(tag,mismatch,mae)
        assert np.count_nonzero(got)>2000
        comparisons.append(dict(tag=tag,mismatched_fraction=mismatch,rgb_mae=mae))
        frames.append(got.ravel())
    report=verify_pixels(out,lambda tag:frames[tag],width=width,height=height,video_720p=hd)
    assert report['captured_tags']==[0,1,2]
    assert not np.array_equal(frames[0],frames[1]),'Live state did not change the image'
    for f,digest in hashes.items():assert hashlib.sha256(Path(f).read_bytes()).hexdigest()==digest
    report.update(passed=True,physics_steps=16,policy_updates=1,exact_state_words=320,
        renderer='unmodified MuJoCo 3.15.0 mjr_render + bounded TinyGL software backend',
        rtl_counts=dict(zip(('cycles','core0_launches','core1_launches','framebuffer_words','submitted_frames','mjr_render_entries'),map(int,counts.groups()))),
        native_image_comparisons=comparisons,
        publications=[dict(tag=int(t),cycle=int(c)) for t,c in re.findall(r'PUBLISH tag=(\d+) cycle=(\d+)',log)],
        scope='Actual RV32, dual TPU, compiled MJX learning/kinematics, MuJoCo C renderer, RGB565 and digital HDMI RTL. No physical board execution or real-time performance claim.',
        sha256=hashes)
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='sha256'},indent=2))
    return report
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out',type=Path);parser.add_argument('firmware',nargs='?',type=Path)
    parser.add_argument('--video-mode',choices=('vga','720p'),default='vga')
    args=parser.parse_args()
    check(args.out.resolve(),args.firmware.resolve() if args.firmware else None,args.video_mode)
