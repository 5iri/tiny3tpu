"""Build MuJoCo's actual C renderer with a bounded TinyGL software backend."""
from pathlib import Path
import subprocess,sys
from generate_gl import generate,ROOT
from export_scene import export

HERE=Path(__file__).resolve().parent
MJ=ROOT/'third_party/mujoco_renderer'
TGL=ROOT/'third_party/tinygl'

def sources(out):
    generate(out)
    return [HERE/'renderer.c',HERE/'gl_port.c',out/'gl_dispatch.c',
        *(MJ/'src/render/classic'/f for f in ('render_context.c','render_gl3.c','render_gl2.c','render_util.c')),
        *(MJ/'src/engine'/f for f in ('engine_vis_init.c','engine_vis_interact.c','engine_util_blas.c','engine_util_spatial.c','engine_util_misc.c')),
        *(f for f in sorted((TGL/'src').glob('*.c')) if f.name not in ('memory.c','msghandling.c'))]

def flags(out):
    return ['-O2','-DTINY3TPU_RENDERER=1','-include','inttypes.h','-std=c11','-ffp-contract=off','-ffunction-sections','-fdata-sections',
        '-Wno-unused-parameter','-Wno-unknown-pragmas','-Wno-incompatible-pointer-types-discards-qualifiers',
        *['-I'+str(p) for p in [HERE,out,MJ/'include',MJ/'src',TGL/'include',TGL/'src']]]

def native(out):
    out.mkdir(parents=True,exist_ok=True);export(out)
    cmd=['clang','-DRENDER_HEAP_BYTES=2097152',*flags(out),*map(str,sources(out)),str(HERE/'native_main.c'),'-Wl,-dead_strip','-lm','-o',str(out/'render-native')]
    (out/'native-command.txt').write_text(' '.join(cmd)+'\n')
    with (out/'native-build.log').open('w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    if r.returncode:raise RuntimeError((out/'native-build.log').read_text()[-10000:])
    return out/'render-native'

def riscv_objects(out,heap_bytes=512*1024):
    from concurrent.futures import ThreadPoolExecutor
    obj=out/'render-objects';obj.mkdir(parents=True,exist_ok=True)
    fs=[f.replace('-std=c11','-std=gnu11').replace('-O2','-Os') for f in flags(out) if 'incompatible-pointer' not in f]
    def compile_one(source):
        target=obj/(source.stem+'.o')
        command=['riscv64-unknown-elf-gcc','-march=rv32im_zicsr_zifencei','-mabi=ilp32',
                 '-DNDEBUG','-fno-builtin','-msmall-data-limit=0',f'-DRENDER_HEAP_BYTES={heap_bytes}',
                 *['-D'+name+'=__ieee754_'+name for name in ('acos','asin','atan2','exp','log','pow','sqrt','sqrtf','powf','atan2f','log10f')],*fs,'-c',str(source),'-o',str(target)]
        r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (obj/(source.stem+'.log')).write_text(r.stdout)
        (obj/(source.stem+'-command.json')).write_text(__import__('json').dumps(command,indent=2)+'\n')
        if r.returncode:raise RuntimeError(r.stdout)
        return target
    with ThreadPoolExecutor(max_workers=4) as pool:return list(pool.map(compile_one,sources(out)))

if __name__=='__main__':native(Path(sys.argv[1]).resolve())
