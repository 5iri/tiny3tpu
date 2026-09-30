"""Build opt-in lossless pip identifiers; existing route-name behavior stays default."""
import json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
base=Path('/tmp/tiny3tpu-nextpnr-pinmap-preservation/build-manifest.json');old=json.loads(base.read_text());assert old['passed'];tool=base.parent/'nextpnr-xilinx';assert digest(tool)==old['tool_sha256'];src=Path('/tmp/tiny3tpu-nextpnr-grade2-guidance/arch.cc');out=Path('/tmp/tiny3tpu-nextpnr-lossless-pre-fixup');assert not out.exists();out.mkdir();text=src.read_text();start=text.index('PipId Arch::getPipByName');pos=text.index('    if (s.substr(0, 8) == "SITEPIP/")',start)
decoder='''    if (s.substr(0, 7) == "PIPIDX/") {
        auto value = split_identifier_name(s.substr(7));
        auto tile = tile_by_name.find(value.first);
        if (tile == tile_by_name.end() || value.second.empty() ||
            value.second.find_first_not_of("0123456789") != std::string::npos)
            log_error("Invalid lossless pip name: %s\\n", s.c_str());
        ret.tile = tile->second;
        try { ret.index = std::stoi(value.second); }
        catch (const std::exception &) { log_error("Invalid lossless pip index: %s\\n", s.c_str()); }
        if (ret.index < 0 || ret.index >= chip_info->tile_types[chip_info->tile_insts[ret.tile].type].num_pips)
            log_error("Out-of-range lossless pip index: %s\\n", s.c_str());
        pip_by_name_cache[name] = ret;
        return ret;
    }
'''
text=text[:pos]+decoder+text[pos:];start=text.index('IdString Arch::getPipName');pos=text.index('    const auto &loc_info',start)
encoder='''    const char *lossless = std::getenv("TINY3TPU_LOSSLESS_ROUTE_NAMES");
    if (lossless && std::string(lossless) == "1")
        return id(std::string("PIPIDX/") + chip_info->tile_insts[pip.tile].name.get() + "/" + std::to_string(pip.index));
'''
text=text[:pos]+encoder+text[pos:]
text='#include "jsonwrite.h"\n'+text
needle='    routeVcc();\n    fixupRouting();'
assert text.count(needle)==1
replacement='''    routeVcc();
    if (const char *snapshot = std::getenv("TINY3TPU_PRE_FIXUP_JSON")) {
        archInfoToAttributes();
        std::string filename(snapshot);
        std::ofstream output(filename);
        if (!output || !write_json_file(output, filename, getCtx()))
            log_error("Failed to write pre-fixup routing checkpoint: %s\\n", snapshot);
    }
    fixupRouting();'''
text=text.replace(needle,replacement)
patched=out/'arch.cc';patched.write_text(text);compile=old['compile'].copy()
for flag,val in [('-MT',str(out/'arch.o')),('-MF',str(out/'arch.o.d')),('-o',str(out/'arch.o')),('-c',str(patched))]:compile[compile.index(flag)+1]=val
compile.insert(1,'-I/tmp/tiny3tpu-nextpnr-grade2-guidance');link=old['link'].copy();idx=next(i for i,v in enumerate(link) if v.endswith('/tiny3tpu-nextpnr-grade2-guidance/arch.o'));link[idx]=str(out/'arch.o');link[link.index('-o')+1]=str(out/'nextpnr-xilinx');builddir=Path('/tmp/tiny3tpu-nextpnr-current/build');inputs=[base,tool,src,Path(__file__).resolve()]+[(builddir/v).resolve() for v in link if v.endswith('.o') and v!=str(out/'arch.o')];hashes={str(q.resolve()):digest(q) for q in inputs};manifest=dict(passed=False,scope='Opt-in lossless pip serialization and exact index decoding only. Full routing and replay controls pending.',compile=compile,link=link,sha256=hashes,source_sha256=digest(patched))
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
for cmd,name in [(compile,'compile.log'),(link,'link.log')]:
 with (out/name).open('w') as f:subprocess.run(cmd,cwd=builddir,stdout=f,stderr=subprocess.STDOUT,check=True)
assert all(digest(n)==h for n,h in hashes.items());manifest.update(passed=True,baseline_unchanged=True,tool_sha256=digest(out/'nextpnr-xilinx'));(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Built isolated lossless route-name tool; routing/replay controls pending')
