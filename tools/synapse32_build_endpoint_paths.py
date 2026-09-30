#!/usr/bin/env python3
"""Build an isolated endpoint report observer without changing timing calculations."""
import argparse,difflib,hashlib,json,shlex,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
base=Path('/tmp/tiny3tpu-nextpnr-current');build=base/'build';out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source=base/'common/timing.cc';original=source.read_text()
marker='                            auto path_budget = period - endpoint_arrival;'
assert original.count(marker)==1
addition='\n                            if (report_endpoints && ctx->getDelayNS(endpoint_arrival) >= 9.0 &&\n                                startdomain.first.clock != async_clock && clksig != async_clock) {\n                                log_info("ENDPOINT %.6f %.6f %s %d %s %d %s %s\\n",\n                                         ctx->getDelayNS(endpoint_arrival), ctx->getDelayNS(period),\n                                         startdomain.first.clock.c_str(ctx), int(startdomain.first.edge),\n                                         clksig.c_str(ctx), int(edge), usr.cell->name.c_str(ctx), usr.port.c_str(ctx));\n                            }\n'
addition += '\n                            if (report_endpoints && endpoint_arrival > period &&\n                                startdomain.first.clock != async_clock && clksig != async_clock) {\n                                NetInfo *trace_net = net;\n                                const PortRef *trace_sink = &usr;\n                                for (int depth = 0; trace_net && trace_net->driver.cell && depth < 128; ++depth) {\n                                    log_info("ENDSTEP %s %s %s %s %s %s %.6f\\n",\n                                             usr.cell->name.c_str(ctx), usr.port.c_str(ctx),\n                                             trace_net->driver.cell->name.c_str(ctx), trace_net->driver.port.c_str(ctx),\n                                             trace_sink->cell->name.c_str(ctx), trace_sink->port.c_str(ctx),\n                                             ctx->getDelayNS(ctx->getNetinfoRouteDelay(trace_net, *trace_sink)));\n                                    const PortInfo *latest = nullptr;\n                                    delay_t latest_arrival = std::numeric_limits<delay_t>::min();\n                                    for (const auto &p : trace_net->driver.cell->ports) {\n                                        if (p.second.type != PORT_IN || !p.second.net) continue;\n                                        DelayInfo comb;\n                                        if (!ctx->getCellDelay(trace_net->driver.cell, p.first, trace_net->driver.port, comb)) continue;\n                                        int clocks;\n                                        auto cls = ctx->getPortTimingClass(trace_net->driver.cell, p.first, clocks);\n                                        if (cls == TMG_CLOCK_INPUT || cls == TMG_ENDPOINT || cls == TMG_IGNORE) continue;\n                                        if (!net_data.count(p.second.net) || !net_data.at(p.second.net).count(startdomain.first)) continue;\n                                        auto arrival = net_data.at(p.second.net).at(startdomain.first).max_arrival;\n                                        if (net_delays) {\n                                            for (auto &u : p.second.net->users)\n                                                if (u.port == p.first && u.cell == trace_net->driver.cell) {\n                                                    arrival += ctx->getNetinfoRouteDelay(p.second.net, u); break;\n                                                }\n                                        }\n                                        arrival += comb.maxDelay();\n                                        if (arrival > latest_arrival) {latest_arrival = arrival; latest = &p.second;}\n                                    }\n                                    if (!latest) break;\n                                    const PortRef *next_sink = nullptr;\n                                    for (auto &u : latest->net->users)\n                                        if (u.cell == trace_net->driver.cell && u.port == latest->name) {next_sink = &u; break;}\n                                    if (!next_sink) break;\n                                    trace_net = latest->net; trace_sink = next_sink;\n                                }\n                            }\n'
candidate=original.replace('    IdString async_clock;', '    IdString async_clock;\n    bool report_endpoints = false;')
candidate=candidate.replace(marker,marker+addition)
marker2='        Timing timing(ctx, true /* net_delays */, false /* update */, &crit_paths, nullptr);'
assert candidate.count(marker2)==1
candidate=candidate.replace(marker2,marker2+'\n        timing.report_endpoints = getenv("TINY3TPU_ENDPOINT_REPORT") != nullptr;')
(out/'timing.cc').write_text(candidate)
(out/'timing.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile='original/timing.cc',tofile='endpoint-report/timing.cc')))
obj='CMakeFiles/nextpnr-xilinx.dir/common/timing.cc.o'
commands=lambda target:subprocess.check_output(['ninja','-C',str(build),'-t','commands',target],text=True).splitlines()[-1]
compile_args=shlex.split(commands(obj));assert str(source) in compile_args
compile_args=[str(out/'timing.cc') if x==str(source) else str(out/'timing.o') if x==obj else str(out/'timing.o.d') if x==obj+'.d' else x for x in compile_args]
link_parts=shlex.split(commands('nextpnr-xilinx'));assert link_parts[:2]==[':','&&'] and link_parts[-2:]==['&&',':'];link_args=link_parts[2:-2]
assert link_args.count(obj)==1
original_inputs=[build/x for x in link_args if x.endswith('.o')]+[Path(x) for x in link_args if x.endswith('.dylib')]
original_inputs += [source,build/'nextpnr-xilinx',Path(__file__).resolve()]
hashes={str(p):digest(p) for p in original_inputs}
link_args=[str(out/'timing.o') if x==obj else x for x in link_args];link_args[link_args.index('-o')+1]=str(out/'nextpnr-xilinx')
record={'scope':'Only optional endpoint logging is added to timing.cc during report JSON generation. All timing equations, placement, routing and checks remain unchanged. All other original link objects are unchanged.','compile':compile_args,'link':link_args,'baseline_sha256':hashes,'source_sha256':digest(out/'timing.cc'),'patch_sha256':digest(out/'timing.patch'),'passed':False}
(out/'build-manifest.json').write_text(json.dumps(record,indent=2)+'\n')
with (out/'compile.log').open('w') as log:rc=subprocess.run(compile_args,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
if rc:raise SystemExit('Compile failed; inspect '+str(out/'compile.log'))
with (out/'link.log').open('w') as log:rc=subprocess.run(link_args,cwd=build,stdout=log,stderr=subprocess.STDOUT).returncode
if rc:raise SystemExit('Link failed; inspect '+str(out/'link.log'))
record['baseline_unchanged']=all(digest(n)==s for n,s in hashes.items())
record['tool_sha256']=digest(out/'nextpnr-xilinx');record['object_sha256']=digest(out/'timing.o')
version=subprocess.run([str(out/'nextpnr-xilinx'),'--version'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
record['version']=version.stdout;record['passed']=record['baseline_unchanged'] and version.returncode==0
(out/'build-manifest.json').write_text(json.dumps(record,indent=2)+'\n')
if not record['passed']:raise SystemExit('Router build verification failed')
print('PASS isolated endpoint reporter build; baseline objects/tool unchanged',record['tool_sha256'])
