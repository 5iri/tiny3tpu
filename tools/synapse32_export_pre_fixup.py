#!/usr/bin/env python3
"""Capture the legal placement before pin legalization; verify original output."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--checkpoint',type=Path,required=True)
p.add_argument('--exporter',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args();digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
checkpoint=a.checkpoint.resolve();cp_manifest=checkpoint.with_name('manifest.json');cp=json.loads(cp_manifest.read_text())
assert cp['exit_code']==0 and cp['inputs_unchanged'] and not cp['placement_changes']
assert digest(checkpoint)==cp['placed_sha256']
for n,s in cp['sha256'].items():assert digest(n)==s,n
binary=a.exporter.resolve();bm=binary.with_name('build-manifest.json');b=json.loads(bm.read_text())
assert b['passed'] and b['baseline_unchanged'] and digest(binary)==b['tool_sha256']
for n,s in b['baseline_sha256'].items():assert digest(n)==s,n
for n,k in [('arch.cc','source_sha256'),('arch.patch','patch_sha256'),('arch.o','object_sha256')]:assert digest(binary.with_name(n))==b[k]
out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
cmd=list(cp['command']);cmd[0]=str(binary)
for flag,v in [('--write',out/'placed.json'),('--report',out/'report.json'),('--log',out/'place.log')]:cmd[cmd.index(flag)+1]=str(v)
assert '--no-route' in cmd and '--no-pack' not in cmd
assert not any(x in cmd for x in ['--force','--timing-allow-fail','--ignore-loops','--fasm'])
sha=dict(cp['sha256']);sha.update({str(p):digest(p) for p in [checkpoint,cp_manifest,bm,binary,Path(__file__).resolve()]})
record={'parent':cp['parent'],'original_checkpoint':str(checkpoint),'command':cmd,'sha256':sha,'scope':'Optional exporter observes the legal pre-fixup placement. Original checks and fixup run normally afterward; final output must exactly equal the original checkpoint.'}
env={k:v for k,v in os.environ.items() if not k.startswith('NEXTPNR_')};env['TINY3TPU_PRE_FIXUP_CHECKPOINT']=str(out/'pre-fixup.json');record['environment']={'TINY3TPU_PRE_FIXUP_CHECKPOINT':env['TINY3TPU_PRE_FIXUP_CHECKPOINT']}
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
with (out/'console.log').open('w') as f:rc=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
record['exit_code']=rc;record['inputs_unchanged']=all(digest(n)==s for n,s in sha.items())
if rc==0:
 old=json.loads(checkpoint.read_text());new=json.loads((out/'placed.json').read_text())
 record['final_checkpoint_exact']=old==new
 record['pre_fixup_sha256']=digest(out/'pre-fixup.json');record['placed_sha256']=digest(out/'placed.json')
record['passed']=rc==0 and record['inputs_unchanged'] and record.get('final_checkpoint_exact',False)
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
print({k:v for k,v in record.items() if k not in ['sha256','command']})
if not record['passed']:raise SystemExit('Pre-fixup capture did not reproduce original output')
