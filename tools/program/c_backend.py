"""Liveness-planned C emission for lowered StableHLO operations."""
from pathlib import Path
import numpy as np
from ._schedule import ProgramError
from .target import CPU, legalize
from .optimize import elementwise_groups
import re
from collections import defaultdict

def emit_c(program, path, *, target=CPU, math_mode='libm', allow_approximation=False, symbol='t3p', fusion=True):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', symbol):
        raise ProgramError('symbol must be a C identifier beginning with a letter')
    if math_mode not in ('libm', 'freestanding'):
        raise ProgramError('math_mode must be libm or freestanding')
    p=program;p.validate();live=p.dce();nodes=p.nodes
    placement=legalize(p,target,math_mode=math_mode,allow_approximation=allow_approximation)
    devices={item['value']:item['device'] for item in placement}
    groups,inlined=elementwise_groups(p,devices) if fusion else ({},set())
    ctypes={'float32':'float','int32':'int32_t','uint32':'uint32_t','bool':'uint8_t','int8':'int8_t','uint8':'uint8_t'}
    aliases={}
    def root(i):
        while i in aliases:i=aliases[i]
        return i
    for n in nodes:
        if n.op=='index' and n.params['map']==list(range(p.values[n.inputs[0]].size)) and p.values[n.output].dtype==p.values[n.inputs[0]].dtype:
            aliases[n.output]=root(n.inputs[0])
    users=defaultdict(set)
    for n in nodes:
        for i in n.inputs:users[i].add(n.output)
    # Single-consumer static reorders are read-only views. Shared gathers stay
    # materialized so their index calculations are not repeated in many loops.
    views={n.output:n for n in nodes if fusion and n.op=='index' and n.output not in aliases
           and n.output not in p.outputs and len(users[n.output])==1}
    def storage_root(i):
        i=root(i)
        while i in views:i=root(views[i].inputs[0])
        return i
    last={i:-1 for i in live}
    for index,n in enumerate(nodes):
        if n.output in inlined or n.output in views:continue
        group=groups.get(n.output,[n]);local={child.output for child in group}
        for child in group:
            for i in child.inputs:
                if i not in local:last[storage_root(i)]=index
    for i in p.outputs:last[storage_root(i)]=len(nodes)
    offsets={};active=[];free=[];high=0
    def allocate(vid,index):
        nonlocal active,high
        if p.values[vid].data is not None or vid in aliases or vid in inlined or vid in views:return
        keep=[]
        for a in active:
            if last[a]<index:free.append((offsets[a],p.values[a].size))
            else:keep.append(a)
        active=keep
        free.sort();merged=[]
        for off,size in free:
            if merged and merged[-1][0]+merged[-1][1]==off:merged[-1]=(merged[-1][0],merged[-1][1]+size)
            else:merged.append((off,size))
        free[:]=merged;size=p.values[vid].size
        for j,(off,length) in enumerate(free):
            if length>=size:
                offsets[vid]=off;free.pop(j)
                if length>size:free.append((off+size,length-size))
                break
        else:offsets[vid]=high;high+=size
        active.append(vid)
    for vid in p.inputs:allocate(vid,-1)
    for index,n in enumerate(nodes):
        for output in n.outputs:allocate(output,index)
    declarations=[];constants={};map_cache={};const_names={};bit_constants=set();max_packed=1;max_accum=1
    for v in p.values:
        if v.id not in live or v.data is None:continue
        key=(v.dtype,v.data.tobytes())
        if key not in constants:
            name=f'k{len(constants)}';constants[key]=name
            typ=ctypes[v.dtype]
            if v.dtype=='float32':
                if not np.isfinite(v.data).all():
                    typ='uint32_t';bit_constants.add(name)
                    items=[str(int(x))+'U' for x in v.data.view(np.uint32).ravel()]
                else:items=[float(x).hex()+'f' for x in v.data.ravel()]
            else:items=[str(int(x))+('U' if typ=='uint32_t' else '') for x in v.data.ravel()]
            declarations.append(f'static const {typ} {name}[{v.size}]={{'+','.join(items)+'};')
        const_names[v.id]=constants[key]
    def member(v):return 'f' if v.dtype=='float32' else 'u' if v.dtype=='uint32' else 'i'
    scalar_refs={}
    def ref(vid,index='i'):
        if vid in scalar_refs:return scalar_refs[vid]
        vid=root(vid);v=p.values[vid]
        if vid in views:
            node=views[vid]
            return ref(node.inputs[0],map_expr(node.params['map'],index))
        if v.data is not None:
            expr=f'{const_names[vid]}[{index}]'
            return f't3p_f32({expr})' if const_names[vid] in bit_constants else expr
        return f'w[{offsets[root(vid)]}+({index})].{member(v)}'
    def map_expr(mapping,index='i'):
        a=np.asarray(mapping,dtype=np.int32)
        if len(a)==1 or np.all(a==a[0]):return str(int(a[0]))
        d=np.diff(a)
        if np.all(d==d[0]):return f'({int(a[0])}+{int(d[0])}*({index}))'
        for width in (3,2,4,6):
            if len(a)%width==0 and np.all(a>=0):
                blocks=a.reshape(-1,width)
                if np.all(blocks==blocks[:,0,None]+np.arange(width)) and np.all(blocks[:,0]%width==0):
                    return f'({map_expr(blocks[:,0]//width,f"({index})/{width}")}*{width}+({index})%{width})'
        key=tuple(a.tolist())
        if key not in map_cache:
            name=f'map{len(map_cache)}';map_cache[key]=name
            declarations.append(f'static const int32_t {name}[{len(a)}]={{'+','.join(map(str,a))+'};')
        return f'{map_cache[key]}[{index}]'
    def broadcast(vid,shape):
        v=p.values[vid]
        if v.size==1:return ref(vid,'0')
        if v.shape==shape:return ref(vid)
        ids=np.arange(v.size).reshape(v.shape)
        try:ids=np.broadcast_to(ids,shape).ravel()
        except ValueError as exc:raise ProgramError(f'broadcast {v.shape} to {shape}') from exc
        return ref(vid,map_expr(ids))
    nested_headers=[];nested_reports=[];loop_fields=[];loop_bytes=0
    body=['if(!workspace||!outputs)return -1;']
    if p.inputs:body.append('if(!inputs)return -1;')
    for index,vid in enumerate(p.inputs):
        v=p.values[vid]
        body.append(f'if(!inputs[{index}])return -1;')
        body.append(f'for(uint32_t i=0;i<{v.size};i++) {ref(vid)}=((const {ctypes[v.dtype]}*)inputs[{index}])[i];')
    for index in range(len(p.outputs)):body.append(f'if(!outputs[{index}])return -1;')
    def loop(size,statement):body.append(f'for(uint32_t i=0;i<{size};i++){{{statement}}}')
    def wrap(expr,dtype):
        if dtype=='float32':return expr
        if dtype=='int32':return f't3p_i32((uint32_t)({expr}))'
        if dtype=='int8':return f't3p_i8((uint32_t)({expr}))'
        return f'({ctypes[dtype]})({expr})'
    def addition(a,b,dtype):
        return f'({a}+{b})' if dtype=='float32' else wrap(f'(uint32_t)({a})+(uint32_t)({b})',dtype)
    def combine(a,b,dtype,op):
        if op=='add':return addition(a,b,dtype)
        if op=='mul':return f'({a}*{b})' if dtype=='float32' else wrap(f'(uint32_t)({a})*(uint32_t)({b})',dtype)
        if op in ('min','max'):
            return f't3p_{op}({a},{b})' if dtype=='float32' else f'({a}{"<" if op=="min" else ">"}{b}?{a}:{b})'
        if op in ('and','or','xor'):return wrap(f'(uint32_t)({a})'+{'and':'&','or':'|','xor':'^'}[op]+f'(uint32_t)({b})',dtype)
        if op=='set':return b
        if op=='keep':return a
        raise ProgramError(f'unknown reducer {op}')
    def element_expr(n,a):
        out=p.values[n.output]
        ops={'add':'+','add_any':'+','sub':'-','mul':'*','div':'/','lt':'<','le':'<=','gt':'>','ge':'>=','eq':'==','ne':'!='}
        if n.op in ops:expr=f'({a[0]} {ops[n.op]} {a[1]})'
        elif n.op=='neg':expr=f'(-{a[0]})'
        elif n.op=='abs':expr=f'({a[0]}<0?-{a[0]}:{a[0]})'
        elif n.op=='sqrt':expr=f'{"sqrtf" if math_mode=="libm" else "t3p_sqrt"}({a[0]})'
        elif n.op=='acos':expr=f'{"acosf" if math_mode=="libm" else "t3p_acos"}({a[0]})'
        elif n.op=='atan2':expr=f'{"atan2f" if math_mode=="libm" else "t3p_atan2"}({a[0]},{a[1]})'
        elif n.op in ('sin','cos'):expr=f'{n.op+"f" if math_mode=="libm" else "t3p_"+n.op}({a[0]})'
        elif n.op in ('and','or','xor'):expr=combine(a[0],a[1],out.dtype,n.op)
        elif n.op=='not':expr=f'(!{a[0]})' if out.dtype=='bool' else wrap(f'~(uint32_t)({a[0]})',out.dtype)
        elif n.op in ('min','max'):
            expr=f't3p_{n.op}({a[0]},{a[1]})' if out.dtype=='float32' else f'({a[0]} {"<" if n.op=="min" else ">"} {a[1]} ? {a[0]} : {a[1]})'
        elif n.op=='sign':expr=f'({a[0]}>0?1:({a[0]}<0?-1:{a[0]}))'
        elif n.op=='select_n':
            if len(a)!=3:raise ProgramError('select_n supports two cases')
            expr=f'({a[0]}?{a[2]}:{a[1]})'
        elif n.op=='convert_element_type':
            source=p.values[n.inputs[0]]
            if out.dtype=='bool':expr=f'({a[0]}!=0)'
            elif source.dtype=='float32' and out.dtype!='float32':
                expr=f't3p_to_{out.dtype}({a[0]})'
            else:expr=f'({ctypes[out.dtype]})({a[0]})'
        elif n.op=='integer_pow' and n.params['exponent']==2:expr=f'({a[0]}*{a[0]})'
        else:raise ProgramError(f'C lowering missing for {n.op}')
        if out.dtype!='float32':
            if n.op in ('add','add_any','sub','mul'):
                expr=wrap(f'((uint32_t)({a[0]}) {ops[n.op]} (uint32_t)({a[1]}))',out.dtype)
            elif n.op in ('neg','abs'):
                neg=wrap(f'(0U-(uint32_t)({a[0]}))',out.dtype)
                expr=neg if n.op=='neg' else f'({a[0]}<0?{neg}:{a[0]})'
            elif n.op=='integer_pow':expr=wrap(f'(uint32_t)({a[0]})*(uint32_t)({a[0]})',out.dtype)
            elif n.op=='convert_element_type' and source.dtype!='float32' and out.dtype!='bool':expr=wrap(a[0],out.dtype)
        return expr
    def stride(shape,axis):return int(np.prod(shape[axis+1:]))
    def coord(shape,axis,index='i'):return f'((({index})/{stride(shape,axis)})%{shape[axis]})'
    def indexed_address(n,iteration_shape,scatter):
        operand,indices=[p.values[i] for i in n.inputs[:2]];par=n.params
        ivd=par['index_vector_dim']
        window=par['update_window_dims' if scatter else 'offset_dims']
        collapsed=par['inserted_window_dims' if scatter else 'collapsed_slice_dims']
        batching=par['input_batching_dims' if scatter else 'operand_batching_dims']
        index_batching=par['scatter_indices_batching_dims' if scatter else 'start_indices_batching_dims']
        index_map=par['scattered_dims_to_operand_dims' if scatter else 'start_index_map']
        iter_batch=[d for d in range(len(iteration_shape)) if d not in window]
        index_axes=[d for d in range(len(indices.shape)) if d!=ivd]
        index_coords={axis:coord(iteration_shape,d) for axis,d in zip(index_axes,iter_batch)}
        index_base='+'.join(f'({index_coords[d]})*{stride(indices.shape,d)}' for d in index_axes) or '0'
        operand_window=[d for d in range(len(operand.shape)) if d not in collapsed and d not in batching]
        window_coords={axis:coord(iteration_shape,d) for axis,d in zip(operand_window,window)}
        code=['uint32_t address=0;']
        for axis,dim in enumerate(operand.shape):
            start='0'
            if axis in index_map:
                component=index_map.index(axis)
                index=f'({index_base})+{component*stride(indices.shape,ivd) if ivd<len(indices.shape) else 0}'
                start=ref(n.inputs[1],index)
            code.append(f'int64_t position{axis}=(int64_t)({start});')
            if not scatter:
                bound=dim-par['slice_sizes'][axis]
                code.append(f'if(position{axis}<0)position{axis}=0;if(position{axis}>{bound})position{axis}={bound};')
            if axis in batching:
                code.append(f'position{axis}+=(int64_t)({index_coords[index_batching[batching.index(axis)]]});')
            if axis in window_coords:
                code.append(f'position{axis}+=(int64_t)({window_coords[axis]});')
            if scatter:code.append(f'if(position{axis}<0||position{axis}>={dim})continue;')
            code.append(f'address+=(uint32_t)position{axis}*{stride(operand.shape,axis)};')
        return ''.join(code)
    for n in nodes:
        if n.output in aliases or n.output in inlined or n.output in views:continue
        out=p.values[n.output];dest=ref(out.id)
        a=[broadcast(i,out.shape) for i in n.inputs] if n.output not in groups and n.op not in ('index','reduce_sum','scatter-add','concatenate','stack','tpu_affine','matmul','while','reduce','gather','scatter') else []
        if n.output in groups:
            statements=[]
            for child in groups[n.output]:
                value=p.values[child.output]
                operands=[broadcast(i,value.shape) for i in child.inputs]
                name=f'scalar{child.output}'
                statements.append(f'{ctypes[value.dtype]} {name}={element_expr(child,operands)};')
                scalar_refs[child.output]=name
            statements.append(f'{dest}={scalar_refs[n.output]};')
            scalar_refs.clear()
            loop(out.size,''.join(statements))
        elif n.op=='gather':
            loop(out.size,indexed_address(n,out.shape,False)+f'{dest}={ref(n.inputs[0],"address")};')
        elif n.op=='scatter':
            loop(out.size,f'{dest}={ref(n.inputs[0])};')
            update=p.values[n.inputs[2]];destination=ref(out.id,'address')
            loop(update.size,indexed_address(n,update.shape,True)+f'{destination}={combine(destination,ref(update.id),out.dtype,n.params["reducer"])};')
        elif n.op=='reduce':
            loop(out.size,f'{dest}={ref(n.inputs[1],"0")};')
            destination=ref(out.id,map_expr(n.params['map']))
            loop(p.values[n.inputs[0]].size,f'{destination}={combine(destination,ref(n.inputs[0]),out.dtype,n.params["reducer"])};')
        elif n.op=='while':
            label=f'loop{n.output}';count=n.params['carry_count'];region_names=[];sizes=[]
            for role,region in zip(('cond','body'),n.params['regions']):
                name=f'{symbol}_{label}_{role}';region_names.append(name)
                code,report=emit_c(region,None,target=target,math_mode=math_mode,
                                   allow_approximation=allow_approximation,symbol=name,fusion=fusion)
                nested_headers.append(code);nested_reports.append(report);sizes.append(report['workspace_bytes'])
            fields=[];size=0
            for index,vid in enumerate(n.inputs):
                v=p.values[vid];fields.append(f'{ctypes[v.dtype]} arg{index}[{v.size}];')
                alignment=min(4,np.dtype(v.dtype).itemsize);size=(size+alignment-1)//alignment*alignment
                size+=v.size*np.dtype(v.dtype).itemsize
            fields.append(f'union {{{region_names[0]}_workspace cond;{region_names[1]}_workspace body;}} scratch;')
            loop_fields.append('struct {'+''.join(fields)+f'}} {label};')
            loop_bytes+=(size+3)//4*4+max(sizes)
            body.append('{')
            for index,vid in enumerate(n.inputs):
                loop(p.values[vid].size,f'workspace->{label}.arg{index}[i]={ref(vid)};')
            for role,slots in zip(('cond','body'),n.params['bindings']):
                ptrs=','.join(f'workspace->{label}.arg{s}' for s in slots) or '0'
                body.append(f'const void *{role}_inputs[]={{'+ptrs+'};')
            body.append('uint8_t predicate;void *cond_outputs[]={&predicate};')
            body.append('void *body_outputs[]={'+','.join(f'workspace->{label}.arg{i}' for i in range(count))+'};')
            body.append('for(;;){')
            body.append(f'int status={region_names[0]}_run(cond_inputs,cond_outputs,&workspace->{label}.scratch.cond,backend);if(status)return status;if(!predicate)break;')
            body.append(f'status={region_names[1]}_run(body_inputs,body_outputs,&workspace->{label}.scratch.body,backend);if(status)return status;')
            body.append('}')
            for index,vid in enumerate(n.outputs):
                loop(p.values[vid].size,f'{ref(vid)}=workspace->{label}.arg{index}[i];')
            body.append('}')
        elif n.op=='matmul':
            lhs,rhs=[p.values[i] for i in n.inputs];m,k=lhs.shape[-2:];cols=rhs.shape[-1]
            batches=lhs.shape[0] if len(lhs.shape)==3 else 1
            body.append(f'for(uint32_t batch=0;batch<{batches};batch++){{')
            if devices[out.id]=='tpu':
                body.append('if(!backend||!backend->run)return -5;')
                max_packed=max(max_packed,m*k+k*cols);max_accum=max(max_accum,m*cols)
                loop(m*k,f'workspace->packed[i]=(int8_t){ref(lhs.id,f"batch*{m*k}+i")};')
                loop(k*cols,f'workspace->packed[{m*k}+i]=(int8_t){ref(rhs.id,f"batch*{k*cols}+i")};')
                body.append(f'if(backend->run(backend->user,workspace->packed,workspace->packed+{m*k},workspace->accum,{m},{k},{cols}))return -5;')
                loop(m*cols,f'{ref(out.id,f"batch*{m*cols}+i")}=workspace->accum[i];')
            else:
                typ='float' if out.dtype=='float32' else 'int32_t'
                body.append(f'for(uint32_t i=0;i<{m};i++)for(uint32_t j=0;j<{cols};j++){{{typ} sum=0;for(uint32_t t=0;t<{k};t++)sum+={ref(lhs.id,f"batch*{m*k}+i*{k}+t")}*{ref(rhs.id,f"batch*{k*cols}+t*{cols}+j")};{ref(out.id,f"batch*{m*cols}+i*{cols}+j")}=sum;}}')
            body.append('}')
        elif n.op=='tpu_affine':
            body.append('if(!backend||!backend->run)return -5;')
            k=len(n.inputs);cols=out.shape[1];digits=n.params['digits'];scale=1<<n.params['fraction_bits']
            for g,group in enumerate(n.params['groups']):
                rows=len(group['rows']);max_packed=max(max_packed,rows*digits*k);max_accum=max(max_accum,rows*digits*cols)
                wname=f'tpu_weights_{n.output}_{g}';flat=np.asarray(group['weights']).ravel()
                declarations.append(f'static const int8_t {wname}[{len(flat)}]={{'+','.join(map(str,flat))+'};')
                body.append('{')
                rowmap=map_expr(group['rows'])
                for c,vid in enumerate(n.inputs):
                    source=ref(vid,rowmap)
                    loop(rows,f'float scaled={source}*{float(scale).hex()}f;if(!t3p_finite(scaled)||scaled>=2147483520.f||scaled< -2147483520.f)return -4;int32_t remain=(int32_t)(scaled+(scaled<0?-.5f:.5f));for(uint32_t digit=0;digit<{digits};digit++){{int32_t low=(int32_t)(((uint32_t)remain+128U)&255U)-128;workspace->packed[(digit*{rows}+i)*{k}+{c}]=(int8_t)low;remain=(remain-low)/256;}}if(remain)return -4;')
                body.append(f'if(backend->run(backend->user,workspace->packed,{wname},workspace->accum,{rows*digits},{k},{cols}))return -5;')
                for c in range(cols):
                    terms='+'.join(f'((int64_t)workspace->accum[({d*rows}+i)*{cols}+{c}]*INT64_C({256**d}))' for d in range(digits))
                    loop(rows,f'{ref(out.id,f"({rowmap})*{cols}+{c}")}=(float)({terms})/{float(scale).hex()}f;')
                body.append('}')
        elif n.op=='index':loop(out.size,f'{dest}={ref(n.inputs[0],map_expr(n.params["map"]))};')
        elif n.op=='reduce_sum':
            loop(out.size,f'{dest}=0;')
            destination=ref(out.id,map_expr(n.params['map']))
            loop(p.values[n.inputs[0]].size,f'{destination}={addition(destination,ref(n.inputs[0]),out.dtype)};')
        elif n.op=='scatter-add':
            loop(out.size,f'{dest}={ref(n.inputs[0])};')
            target_index=map_expr(n.params['map']);destination=ref(out.id,'t')
            loop(len(n.params['map']),f'int32_t t={target_index};if(t>=0) {destination}={addition(destination,ref(n.inputs[1]),out.dtype)};')
        elif n.op in ('concatenate','stack'):
            labels=[];start=0
            for vid in n.inputs:
                v=p.values[vid];labels.append(np.arange(start,start+v.size).reshape(v.shape));start+=v.size
            mapping=(np.concatenate if n.op=='concatenate' else np.stack)(labels,axis=n.params['axis']).ravel();start=0
            for vid in n.inputs:
                size=p.values[vid].size;targets=np.empty(size,np.int32)
                for target_index,source in enumerate(mapping):
                    if start<=source<start+size:targets[source-start]=target_index
                loop(size,f'{ref(out.id,map_expr(targets))}={ref(vid)};');start+=size
        else:
            loop(out.size,f'{dest}={element_expr(n,a)};')
    for index,vid in enumerate(p.outputs):
        v=p.values[vid]
        loop(v.size,f'(({ctypes[v.dtype]}*)outputs[{index}])[i]={ref(vid)};')
    high=max(1,high)
    guard=symbol.upper()+'_GENERATED_PROGRAM_H'
    header=[f'#ifndef {guard}',f'#define {guard}','#include <stdint.h>','#include "tiny3tpu_program_math.h"','#include "tiny3tpu_runtime.h"']
    if math_mode=='libm':header.append('#include <math.h>')
    header += nested_headers
    header += [f'#define {symbol.upper()}_INPUT_COUNT {len(p.inputs)}',f'#define {symbol.upper()}_OUTPUT_COUNT {len(p.outputs)}',f'#define {symbol.upper()}_WORKSPACE_WORDS {high}',
               f'typedef union {{float f;int32_t i;uint32_t u;}} {symbol}_word;',
               f'typedef struct {{{symbol}_word values[{high}];int8_t packed[{max_packed}];int32_t accum[{max_accum}];'+''.join(loop_fields)+f'}} {symbol}_workspace;']
    for kind,ids in (('INPUT',p.inputs),('OUTPUT',p.outputs)):
        for index,vid in enumerate(ids):
            header.append(f'#define {symbol.upper()}_{kind}_{index}_ELEMENTS {p.values[vid].size}')
    text='\n'.join(header+declarations+[f'static inline int {symbol}_run(const void *const *inputs,void *const *outputs,{symbol}_workspace *workspace,const tiny3tpu_qgemm_backend *backend) {{',
            f'{symbol}_word *w=workspace?workspace->values:0;(void)w;(void)backend;(void)inputs;']+body+['return 0;}','#endif',''])
    # Internal tables must also be namespaced so multiple programs share a translation unit.
    text=re.sub(r'\b(k[0-9]+|map[0-9]+|tpu_weights_[0-9]+_[0-9]+)\b',lambda m:symbol+'_'+m[0],text)
    memory={'workspace_bytes':high*4+((max_packed+3)//4)*4+max_accum*4+loop_bytes,
            'constant_bytes':sum(len(k[1]) for k in constants)+sum(r['constant_bytes'] for r in nested_reports),
            'map_bytes':sum(len(k)*4 for k in map_cache)+sum(r['map_bytes'] for r in nested_reports),
            'tpu_weight_bytes':sum(len(g['weights'])*len(g['weights'][0]) for n in nodes if n.op=='tpu_affine' for g in n.params['groups'])+sum(r['tpu_weight_bytes'] for r in nested_reports),
            'source_bytes':len(text)}
    if target.workspace_limit_bytes is not None and memory['workspace_bytes']>target.workspace_limit_bytes:
        raise ProgramError(f'{target.name}: workspace requires {memory["workspace_bytes"]} bytes, limit is {target.workspace_limit_bytes}')
    report={**memory,'fusion':{'groups':len(groups),'eliminated_arrays':len(inlined),'index_views':len(views)},
        'placement':placement,'regions':nested_reports,'signature':{
        name:[{'id':i,'dtype':p.values[i].dtype,'shape':p.values[i].shape,'bytes':p.values[i].size*np.dtype(p.values[i].dtype).itemsize} for i in ids]
        for name,ids in (('inputs',p.inputs),('outputs',p.outputs))}}
    if path is None:return text,report
    Path(path).write_text(text)
    return report
