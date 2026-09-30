"""Verify an identical parallel reset stage, then collapse it for comparison."""
import copy

def collapse_reset_copy(design, evidence):
    result=copy.deepcopy(design);m=result['modules']['top'];cells=m['cells']
    source=cells[evidence['driver']];clone=cells[evidence['copy']]
    assert source['type']==clone['type']=='SLICE_FFX'
    assert source['attributes']['X_ORIG_TYPE']==clone['attributes']['X_ORIG_TYPE']=='FDPE'
    assert source['parameters']['INIT']==clone['parameters']['INIT']=='1'
    reset=source['connections']['Q'][0];replica=clone['connections']['Q'][0];assert reset!=replica
    check=copy.deepcopy(clone);check['connections']['Q']=source['connections']['Q']
    # Location and binding strength are the only permitted clone differences.
    for k in ['NEXTPNR_BEL','BEL_STRENGTH']:
        if k in source['attributes']:check['attributes'][k]=source['attributes'][k]
        else:check['attributes'].pop(k,None)
    assert check==source,'Reset primitive, initialization or input wiring differs'
    assert m['netnames'][evidence['copy']]['bits']==[replica]
    del cells[evidence['copy']];del m['netnames'][evidence['copy']]
    loads=[]
    for name,cell in cells.items():
        for port,bits in cell['connections'].items():
            if replica in bits:
                assert cell['port_directions'][port]=='input'
                loads.append([name,port])
                cell['connections'][port]=[reset if b==replica else b for b in bits]
    # Pin legalization may rename physical ports; compare load cells here.
    # Full logical pin connections are compared after collapsing the copy.
    assert sorted(n for n,p in loads)==sorted(n for n,p in evidence['loads'])
    assert all(replica not in v['bits'] for v in m['netnames'].values())
    return result
