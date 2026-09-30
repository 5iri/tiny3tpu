"""Build opt-in decoding for the exact routing names emitted by this backend."""
import json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
base=Path('/tmp/tiny3tpu-nextpnr-pinmap-preservation/build-manifest.json');old=json.loads(base.read_text());assert old['passed'];tool=base.parent/'nextpnr-xilinx';assert digest(tool)==old['tool_sha256'];src=Path('/tmp/tiny3tpu-nextpnr-grade2-guidance/arch.cc');out=Path('/tmp/tiny3tpu-nextpnr-route-name-replay');assert not out.exists();out.mkdir();text=src.read_text();start=text.index('PipId Arch::getPipByName');pos=text.index('    if (s.substr(0, 8) == "SITEPIP/")',start)
insert='''    // Opt-in replay decoder: match the exact name emitted by getPipName.
    // Refuse ambiguous names rather than silently picking a different pip.
    const char *replay_names = std::getenv("TINY3TPU_ROUTE_NAME_REPLAY");
    if (replay_names && std::string(replay_names) == "1" &&
        (s.substr(0, 8) == "SITEPIP/" || s.find("->") != std::string::npos)) {
        int matches = 0;
        auto consider = [&](PipId candidate) {
            if (getPipName(candidate) == name) {
                ret = candidate;
                ++matches;
            }
        };
        auto arrow = s.find("->");
        if (arrow != std::string::npos) {
            WireId source = getWireByName(id(s.substr(0, arrow)));
            if (source == WireId())
                log_error("Replay pip has unknown source: %s\\n", s.c_str());
            for (PipId candidate : getPipsDownhill(source))
                consider(candidate);
        } else {
            auto site_name = split_identifier_name(s.substr(8)).first;
            auto found = site_by_name.find(site_name);
            if (found == site_by_name.end())
                log_error("Replay pip has unknown site: %s\\n", s.c_str());
            int tile = found->second.first, site = found->second.second;
            const auto &td = chip_info->tile_types[chip_info->tile_insts[tile].type];
            for (int i = 0; i < td.num_pips; ++i) {
                if (td.pip_data[i].site == site) {
                    PipId candidate; candidate.tile = tile; candidate.index = i;
                    consider(candidate);
                }
            }
        }
        if (matches != 1)
            log_error("Replay pip name has %d matches (expected exactly one): %s\\n", matches, s.c_str());
        pip_by_name_cache[name] = ret;
        return ret;
    }
'''
text=text[:pos]+insert+text[pos:];patched=out/'arch.cc';patched.write_text(text);compile=old['compile'].copy()
for flag,val in [('-MT',str(out/'arch.o')),('-MF',str(out/'arch.o.d')),('-o',str(out/'arch.o')),('-c',str(patched))]:compile[compile.index(flag)+1]=val
compile.insert(1,'-I/tmp/tiny3tpu-nextpnr-grade2-guidance');link=old['link'].copy();idx=next(i for i,v in enumerate(link) if v.endswith('/tiny3tpu-nextpnr-grade2-guidance/arch.o'));link[idx]=str(out/'arch.o');link[link.index('-o')+1]=str(out/'nextpnr-xilinx');builddir=Path('/tmp/tiny3tpu-nextpnr-current/build');inputs=[base,tool,src,Path(__file__).resolve()]+[(builddir/v).resolve() for v in link if v.endswith('.o') and v!=str(out/'arch.o')];hashes={str(q.resolve()):digest(q) for q in inputs};manifest=dict(passed=False,scope='Opt-in exact emitted-pip-name decoder only; unchanged replay and disabled control still required',compile=compile,link=link,sha256=hashes,source_sha256=digest(patched))
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
for cmd,name in [(compile,'compile.log'),(link,'link.log')]:
 with (out/name).open('w') as f:subprocess.run(cmd,cwd=builddir,stdout=f,stderr=subprocess.STDOUT,check=True)
assert all(digest(n)==h for n,h in hashes.items());manifest.update(passed=True,baseline_unchanged=True,tool_sha256=digest(out/'nextpnr-xilinx'));(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Built isolated opt-in route-name decoder; controls pending')
