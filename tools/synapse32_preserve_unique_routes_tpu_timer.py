"""Reuse routing only for nets with identical physical endpoints and placement."""
import copy,hashlib,json
from collections import defaultdict
from pathlib import Path

def preserve(candidate,lock=False):
    root=Path(__file__).resolve().parents[1];h=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    mp=root/'build-routing-import-unique-control-mid2-v3/manifest.json';r=json.loads(mp.read_text());assert r['passed'] and r['routed_json_exact'] and r['native_fmax_exact'] and r['inputs_unchanged']
    for n,v in r['sha256'].items():assert h(n)==v,n
    graph=mp.parent/'timing-graph.tsv';assert h(graph)==r['output_sha256'][str(graph)]
    source=Path(r['command'][r['command'].index('--write')+1]);gold=json.loads(source.read_text())
    original=copy.deepcopy(candidate);before=gold['modules']['top'];after=candidate['modules']['top']
    def endpoints(m):
        result=defaultdict(set)
        for n,c in m['cells'].items():
            for pin,bits in c['connections'].items():
                for i,b in enumerate(bits):
                    result[b].add((n,c['type'],pin,i,c['port_directions'][pin],c['attributes']['NEXTPNR_BEL']))
        return result
    be=endpoints(before);ae=endpoints(after);seen=set();kept=[];skipped=0
    for name,net in before['netnames'].items():
        route=net.get('attributes',{}).get('ROUTING','')
        if len(route)<10 or len(net['bits'])!=1 or name not in after['netnames']:continue
        if name.startswith('$PACKER_'):continue
        if name.startswith('memory.main_zqcs_timer_count0['):continue
        if name=='soc.accelerator.transport.accelerator.u_top.GEN_BIG_CORES[1].u_core.a_in[3][3]':continue
        target=after['netnames'][name]
        if len(target['bits'])!=1:continue
        oldbit=net['bits'][0];newbit=target['bits'][0]
        if newbit in seen:continue
        # Require a real driven, used net with exactly identical physical pins.
        if not be[oldbit] or be[oldbit]!=ae[newbit] or not any(x[4]=='output' for x in ae[newbit]):skipped+=1;continue
        # Dedicated clocks are rebuilt normally, including new replica loads.
        if any('CLK' in x[2] or x[2] in ('CK','C') or 'BUFG' in x[1] or 'PLL' in x[1] for x in ae[newbit]):skipped+=1;continue
        parts=route.split(';');assert len(parts)%3==0
        if lock:
            for i in range(2,len(parts),3):
                assert 0<=int(parts[i])<=5
                parts[i]=str(max(4,int(parts[i])))
        target.setdefault('attributes',{})['ROUTING']=';'.join(parts)
        seen.add(newbit);kept.append(name)
    assert len(kept)>10000,(len(kept),skipped)
    check=copy.deepcopy(candidate)
    for name in kept:
        attrs=check['modules']['top']['netnames'][name]['attributes'];attrs.pop('ROUTING')
        if not attrs and 'attributes' not in original['modules']['top']['netnames'][name]:del check['modules']['top']['netnames'][name]['attributes']
    assert check==original,'Only recorded routing attributes may change'
    return dict(scope='Routing is reused only when every physical driver/sink pin, cell type and BEL is identical. Constants and clock nets are rebuilt. No logic or timing arc changes.',preserved_net_count=len(kept),incompatible_net_count=skipped,locked=lock,explicitly_rerouted=['memory.main_zqcs_timer_count0[*]','soc.accelerator.transport.accelerator.u_top.GEN_BIG_CORES[1].u_core.a_in[3][3]'],nets=kept,sha256={str(q):h(q) for q in [mp,source,graph,Path(__file__).resolve(),Path('/tmp/tiny3tpu-nextpnr-current/common/nextpnr.h')]})
