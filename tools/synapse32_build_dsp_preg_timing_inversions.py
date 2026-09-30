#!/usr/bin/env python3
"""Build an isolated DSP PREG timing model with packed-pin inversion support."""
import argparse,difflib,hashlib,json,shlex,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
p.add_argument('--source-dir',type=Path,default=Path('/tmp/tiny3tpu-nextpnr-current'))
p.add_argument('--grade2',action='store_true',help='Use the DS182 -2/-2LE 1.0 V column for KC705 instead of maxima across grades')
a=p.parse_args()
base=a.source_dir.absolute();build=base/'build';out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source=base/'xilinx/arch.cc';original=source.read_text()
model_path=Path('hardware/synapse32/experiments/dsp-preg-timing/model-inversions.inc').resolve()
limits_path=Path('build-dsp-preg-timing/limits.json').resolve();limits=json.loads(limits_path.read_text());assert limits['passed']
for n,h in limits['sha256'].items():assert digest(n)==h,n
model=model_path.read_text()
selected = {}
if a.grade2:
    # Table 35 columns: -3, -2/-2LE (1.0V), -1, -1M/-1LM/-1Q, -2LI, -2LE (0.9V).
    datasheet=Path('build-dsp-preg-timing/ds182.txt').read_text()
    assert 'Units1.0V 0.95V 0.9V\n-3 -2/-2LE -1 -1M/-1LM/' in datasheet
    for key, old in [('AB_setup',5.89),('C_setup',2.11),('CEP_setup',0.54),('RSTP_setup',0.37)]:
        value=limits['limits'][key]['all_grades'][1]
        selected[key]=value
        model=model.replace(str(old),str(value))
    selected['clock_to_Q']=limits['limits']['P_clock_to_Q']['all_grades'][1]
    selected['RSTP_hold']=max(0,limits['limits']['RSTP_setup']['hold_all_grades'][1])
    model=model.replace('maxima across all listed speed/voltage grades','-2/-2LE 1.0 V column (KC705 -2 only)')
candidate=original.replace('bool Arch::place()\n',model+'\nbool Arch::place()\n',1)
old='        if (!dsp48e1IsCombinational(cell))\n            return TMG_IGNORE;\n'
new='        if (!dsp48e1IsCombinational(cell)) {\n            if (!preg_timing_supported(this, cell))\n                log_error("Unsupported registered DSP timing profile: %s\\n", cell->name.c_str(this));\n            auto base = preg_pin_base(this, port);\n            if (base == "CLK") return TMG_CLOCK_INPUT;\n            if (base == "P") {clockInfoCount = 1; return TMG_REGISTER_OUTPUT;}\n            if (preg_setup_ns(base) > 0.0) {clockInfoCount = 1; return TMG_REGISTER_INPUT;}\n            return TMG_IGNORE; // Guard verified every remaining connected input is constant.\n        }\n'
assert candidate.count(old)==1;candidate=candidate.replace(old,new)
old='    TimingClockingInfo info;'
new='    TimingClockingInfo info;\n    if (cell->type == id("DSP48E1_DSP48E1") && !dsp48e1IsCombinational(cell)) {\n        if (!preg_timing_supported(this, cell))\n            log_error("Unsupported registered DSP timing profile: %s\\n", cell->name.c_str(this));\n        auto base = preg_pin_base(this, port);\n        info.clock_port = id("CLK");\n        info.edge = RISING_EDGE;\n        info.clockToQ = getDelayFromNS(0.45);\n        info.setup = getDelayFromNS(preg_setup_ns(base));\n        info.hold = getDelayFromNS(base == "RSTP" ? 0.11 : base == "CEP" ? 0.01 : 0.0);\n        return info;\n    }\n'
if a.grade2:
    new=new.replace('0.45',str(selected['clock_to_Q'])).replace('0.11',str(selected['RSTP_hold']))
assert candidate.count(old)==1;candidate=candidate.replace(old,new)
marker='    std::string placer = str_or_default(settings, id("placer"), defaultPlacer);'
coverage='    for (auto &entry : cells) {\n        auto c = entry.second.get();\n        if (c->type != id("DSP48E1_DSP48E1") || dsp48e1IsCombinational(c)) continue;\n        if (!preg_timing_supported(this, c))\n            log_error("Unsupported registered DSP timing profile: %s\\n", c->name.c_str(this));\n        int data_inputs = 0, outputs = 0;\n        for (const auto &p : c->ports) {\n            if (!p.second.net) continue;\n            auto base = preg_pin_base(this, p.first);\n            int count = 0;\n            auto cls = getPortTimingClass(c, p.first, count);\n            if (base == "P" || preg_setup_ns(base) > 0.0) {\n                NPNR_ASSERT(count == 1);\n                NPNR_ASSERT(cls == (base == "P" ? TMG_REGISTER_OUTPUT : TMG_REGISTER_INPUT));\n                auto info = getPortClockingInfo(c, p.first, 0);\n                NPNR_ASSERT(info.clock_port == id("CLK"));\n                NPNR_ASSERT(info.setup.maxDelay() == getDelayFromNS(preg_setup_ns(base)).maxDelay());\n                NPNR_ASSERT(info.clockToQ.maxDelay() == getDelayFromNS(0.45).maxDelay());\n                if (base == "P") outputs++; else data_inputs++;\n            }\n        }\n        log_info("DSP_PREG_TIMED %s inputs=%d outputs=%d AB_setup=5.89 C_setup=2.11 CLKQ=0.45\\n",\n                 c->name.c_str(this), data_inputs, outputs);\n    }\n'
if a.grade2:
    coverage=coverage.replace('0.45',str(selected['clock_to_Q']))
    coverage=coverage.replace('AB_setup=5.89 C_setup=2.11 CLKQ=0.45',
                              'AB_setup=3.90 C_setup=1.49 CLKQ=0.35 grade=-2/1.0V')
    coverage=coverage.replace('AB_setup=5.89 C_setup=2.11 CLKQ=0.35',
                              'AB_setup=3.90 C_setup=1.49 CLKQ=0.35 grade=-2/1.0V')
assert candidate.count(marker)==1;candidate=candidate.replace(marker,coverage+marker)
(out/'arch.cc').write_text(candidate)
(out/'arch.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='original/arch.cc',tofile='dsp-preg-timing/arch.cc')))
obj='CMakeFiles/nextpnr-xilinx.dir/xilinx/arch.cc.o'
commands=lambda target:subprocess.check_output(['ninja','-C',str(build),'-t','commands',target],text=True).splitlines()[-1]
compile_args=shlex.split(commands(obj));assert str(source) in compile_args
compile_args=[str(out/'arch.cc') if x==str(source) else str(out/'arch.o') if x==obj else str(out/'arch.o.d') if x==obj+'.d' else x for x in compile_args]
link_parts=shlex.split(commands('nextpnr-xilinx'));assert link_parts[:2]==[':','&&'] and link_parts[-2:]==['&&',':'];link_args=link_parts[2:-2]
assert link_args.count(obj)==1
original_inputs=[build/x for x in link_args if x.endswith('.o')]+[Path(x) for x in link_args if x.endswith('.dylib')]
original_inputs += [source,build/'nextpnr-xilinx',Path(__file__).resolve(),model_path,limits_path]+[Path(n) for n in limits['sha256']]
hashes={str(p):digest(p) for p in original_inputs}
link_args=[str(out/'arch.o') if x==obj else x for x in link_args];link_args[link_args.index('-o')+1]=str(out/'nextpnr-xilinx')
record={'scope':'Add timing coverage for the exact PREG-only DSP MAC profile using AMD DS182 limits. Unsupported registered profiles fail. Existing combinational DSP and all other timing, placement and routing code are unchanged.','selected_grade2_limits':selected,'compile':compile_args,'link':link_args,'baseline_sha256':hashes,'source_sha256':digest(out/'arch.cc'),'patch_sha256':digest(out/'arch.patch'),'passed':False,'timing_model':limits}
(out/'build-manifest.json').write_text(json.dumps(record,indent=2)+'\n')
with (out/'compile.log').open('w') as log:rc=subprocess.run(compile_args,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
if rc:raise SystemExit('Compile failed; inspect '+str(out/'compile.log'))
with (out/'link.log').open('w') as log:rc=subprocess.run(link_args,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
if rc:raise SystemExit('Link failed; inspect '+str(out/'link.log'))
record['baseline_unchanged']=all(digest(n)==s for n,s in hashes.items())
record['tool_sha256']=digest(out/'nextpnr-xilinx');record['object_sha256']=digest(out/'arch.o')
version=subprocess.run([str(out/'nextpnr-xilinx'),'--version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
record['version']=version.stdout;record['passed']=record['baseline_unchanged'] and version.returncode==0
(out/'build-manifest.json').write_text(json.dumps(record,indent=2)+'\n')
if not record['passed']:raise SystemExit('Router build verification failed')
print('PASS isolated registered DSP timing build; baseline objects/tool unchanged',record['tool_sha256'])
