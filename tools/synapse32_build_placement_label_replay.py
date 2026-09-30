"""Preserve imported logical LUT labels through normal placement input merging."""
import json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
base=Path('/tmp/tiny3tpu-nextpnr-pinmap-preservation/build-manifest.json');m=json.loads(base.read_text());parent=Path('/tmp/tiny3tpu-nextpnr-lossless-pre-fixup/manifest.json');pm=json.loads(parent.read_text());assert m['passed'] and pm['passed'];src=base.parent/'arch_place.cc';out=Path('/tmp/tiny3tpu-nextpnr-placement-label-replay');assert not out.exists();out.mkdir();s=src.read_text()
needle='''            // Disconnect LUT inputs, and re-connect them to not overlap
'''
addition='''            // An imported routed LUT already maps physical pins to logical roles.
            // Preserve those roles by signal through the input remerge below.
            std::unordered_map<IdString, std::string> replay5, replay6;
            bool replay_labels = std::getenv("TINY3TPU_REPLAY_PLACEMENT_LABELS") != nullptr;
            if (replay_labels) {
                auto collect = [&](CellInfo *cell, std::unordered_map<IdString, std::string> &labels) {
                    if (!cell) return;
                    for (int p = 1; p <= 6; ++p) {
                        IdString pin = id("A" + std::to_string(p));
                        if (!cell->ports.count(pin) || !cell->ports.at(pin).net) continue;
                        std::string role = str_or_default(cell->attrs, id("X_ORIG_PORT_" + pin.str(this)));
                        auto &value = labels[cell->ports.at(pin).net->name];
                        if (!role.empty()) value += (value.empty() ? "" : " ") + role;
                    }
                };
                collect(lut5, replay5); collect(lut6, replay6);
            }
'''
assert s.count(needle)==1;s=s.replace(needle,addition+needle)
needle='''                ++index;
            }
            rename_port(getCtx(), lut5, id_O6, id_O5);'''
replace='''                if (replay_labels) {
                    if (lut5Inputs.count(i)) lut5->attrs[id("X_ORIG_PORT_" + ports[index].str(this))] = replay5.at(i);
                    if (lut6 && lut6Inputs.count(i)) lut6->attrs[id("X_ORIG_PORT_" + ports[index].str(this))] = replay6.at(i);
                }
                ++index;
            }
            rename_port(getCtx(), lut5, id_O6, id_O5);'''
assert s.count(needle)==1;s=s.replace(needle,replace);patched=out/'arch_place.cc';patched.write_text(s);cc=m['compile'].copy()
for flag,val in [('-MT',str(out/'arch_place.o')),('-MF',str(out/'arch_place.o.d')),('-o',str(out/'arch_place.o')),('-c',str(patched))]:cc[cc.index(flag)+1]=val
link=pm['link'].copy();indices=[i for i,v in enumerate(link) if v.endswith('/arch_place.o')];assert len(indices)==1;link[indices[0]]=str(out/'arch_place.o');link[link.index('-o')+1]=str(out/'nextpnr-xilinx');cwd=Path('/tmp/tiny3tpu-nextpnr-current/build');files=[base,parent,src,Path(__file__).resolve()]+[(cwd/v).resolve() for v in link if v.endswith('.o') and v!=str(out/'arch_place.o')];hashes={str(p):digest(p) for p in files};rec=dict(passed=False,compile=cc,link=link,sha256=hashes,source_sha256=digest(patched),full_soc_timing_accepted=False)
for cmd,name in [(cc,'compile.log'),(link,'link.log')]:
 with (out/name).open('w') as f:subprocess.run(cmd,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,check=True)
assert all(digest(p)==h for p,h in hashes.items());rec.update(passed=True,tool_sha256=digest(out/'nextpnr-xilinx'));(out/'manifest.json').write_text(json.dumps(rec,indent=2)+'\n');print('Build passed; route/equivalence validation pending')
