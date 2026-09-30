"""Discover elementwise affine DAGs and batch repeated integer matrices for TPU."""
import collections
import numpy as np
from ._schedule import Node

def partition_affine(p,coefficient_tolerance=0.0,input_fraction_bits=20,digits=3,*,cost_model=None,policy='auto',decisions=None):
    if policy not in ('auto','force'):raise ValueError('affine policy must be auto or force')
    if not 0<=input_fraction_bits<=30 or not np.isfinite(coefficient_tolerance) or coefficient_tolerance<0:raise ValueError('invalid approximation policy')
    if digits not in (2,3):raise ValueError('supported digit counts: 2 or 3')
    forms={};candidates={}
    for n in p.nodes:
        if n.op not in ('add','add_any','sub','mul','neg'):continue
        out=p.values[n.output];shape=out.shape
        if out.dtype!='float32' or len(shape)!=2:continue
        def form(vid):
            v=p.values[vid]
            if v.data is not None:return ({},np.broadcast_to(v.data,shape).astype(np.float64),set())
            if v.shape!=shape:return None
            return forms.get(vid,({vid:np.ones(shape)},np.zeros(shape),set()))
        fs=[form(i) for i in n.inputs];f=None
        if n.op in ('add','add_any','sub') and all(x is not None for x in fs):
            sign=-1 if n.op=='sub' else 1;r=dict(fs[0][0])
            for k,v in fs[1][0].items():r[k]=r.get(k,0)+sign*v
            f=(r,fs[0][1]+sign*fs[1][1],fs[0][2]|fs[1][2]|{n.output})
        elif n.op=='mul' and all(x is not None for x in fs) and (not fs[0][0] or not fs[1][0]):
            dynamic,constant=(fs[1],fs[0]) if not fs[0][0] else (fs[0],fs[1])
            f=({k:v*constant[1] for k,v in dynamic[0].items()},dynamic[1]*constant[1],dynamic[2]|constant[2]|{n.output})
        elif n.op=='neg' and fs[0] is not None:
            f=({k:-v for k,v in fs[0][0].items()},-fs[0][1],fs[0][2]|{n.output})
        if f is None:continue
        f=({k:v for k,v in f[0].items() if np.any(v!=0)},f[1],f[2]);forms[n.output]=f
        if 1<=len(f[0])<=3 and len(f[2])>=8 and out.size>=32 and np.all(f[1]==0):
            coef=np.stack(list(f[0].values()))
            if np.isfinite(coef).all() and np.max(abs(coef-np.rint(coef)))<=coefficient_tolerance and np.max(abs(coef))<=127 and np.max(abs(coef))>=2:
                candidates[n.output]=f
    # Select terminal eligible forms, avoiding duplicated nested offloads.
    selected={k:v for k,v in candidates.items() if not any(k in other[2] for oid,other in candidates.items() if oid!=k)}
    batches=collections.defaultdict(list)
    for vid,f in selected.items():batches[(p.values[vid].shape,tuple(sorted(f[0])))].append(vid)
    replacements={};newnodes=[];partitions=[]
    for (shape,roots),outputs in batches.items():
        if len(outputs)>4:continue
        coef=np.stack([np.stack([forms[o][0][r] for o in outputs],axis=-1) for r in roots],axis=-2).reshape(-1,len(roots),len(outputs))
        rounded=np.rint(coef).astype(np.int8)
        unique,groups=np.unique(rounded.reshape(len(coef),-1),axis=0,return_inverse=True)
        if len(unique)>8:continue
        group_records=[]
        for g,w in enumerate(unique):group_records.append({'rows':np.where(groups==g)[0].tolist(),'weights':w.reshape(len(roots),len(outputs)).tolist()})
        params={'groups':group_records,'fraction_bits':input_fraction_bits,'digits':digits,'roots':list(roots),'original_outputs':outputs,
                'max_coefficient_error':float(abs(coef-rounded).max()),'replaced_affine_nodes':len(set().union(*(forms[o][2] for o in outputs)))}
        estimate=cost_model.estimate(p,outputs,roots,dict(params,source_nodes={o:forms[o][2] for o in outputs})) if cost_model else None
        selected=policy=='force' or (estimate is not None and estimate['profitable'])
        if decisions is not None:
            decisions.append(dict(outputs=outputs,selected=selected,policy=policy,estimate=estimate,
                reason='forced' if policy=='force' else 'estimated speedup' if selected else
                       'no target cost model' if estimate is None else 'conversion/transport exceed expected savings'))
        if not selected:continue
        params['cost_estimate']=estimate
        combined=p.value((int(np.prod(shape)),len(outputs)),np.float32)
        replacement=Node('tpu_affine',list(roots),combined,params)
        # Roots precede all outputs. Insert at the earliest replaced output.
        order={n.output:i for i,n in enumerate(p.nodes)}
        first=min(outputs,key=lambda o:order[o])
        if any(order.get(r,-1)>=order[first] for r in roots):continue
        for col,vid in enumerate(outputs):
            replacements[vid]=Node('index',[combined],vid,{'map':list(range(col,int(np.prod(shape))*len(outputs),len(outputs)))})
        partitions.append({'first':first,'node':replacement,**params})
    for n in p.nodes:
        for part in partitions:
            if n.output==part['first']:newnodes.append(part['node'])
        newnodes.append(replacements.get(n.output,n))
    p.nodes=newnodes;p.dce()
    return [{k:v for k,v in part.items() if k not in ('node','first')} for part in partitions]
