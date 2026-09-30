#!/usr/bin/env python3
"""Explicit one-hot state encoding for DDR refresher FSM."""
import hashlib,importlib.util,inspect,json,re,runpy,textwrap,types
from pathlib import Path
HERE=Path(__file__).resolve().parent

def patch_fsms(evidence):
    import migen.genlib.fsm as fsm
    from litedram.core.bankmachine import BankMachine
    from litedram.core.refresher import Refresher
    from litedram.core.multiplexer import Multiplexer
    original=textwrap.dedent(inspect.getsource(fsm.FSM.do_finalize))
    candidate=original.replace('dict((s, n) for n, s in enumerate(self.actions.keys()))','dict((s, 1 << n) for n, s in enumerate(self.actions.keys()))')
    assert candidate!=original
    assert candidate.count('Signal(max=nstates')==2
    candidate=candidate.replace('Signal(max=nstates','Signal(nstates')
    namespace=dict(fsm.__dict__);exec(compile(candidate,str(HERE/'onehot_finalize.py'),'exec'),namespace)
    finalize=namespace['do_finalize']
    for cls in [Refresher]:
        old=cls.__init__
        def init(self,*args,_old=old,**kwargs):
            _old(self,*args,**kwargs)
            self.fsm.do_finalize=types.MethodType(finalize,self.fsm)
        cls.__init__=init
    out=Path(evidence);out.mkdir(parents=True,exist_ok=True)
    (out/'original.py').write_text(original);(out/'onehot.py').write_text(candidate)
    paths=[Path(__file__),Path(fsm.__file__),out/'original.py',out/'onehot.py']
    (out/'sources.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+'\n')

def lower_onehot_cases(source,names):
    # Explicit bit tests avoid wide equality comparators on encoded state vectors.
    for name in names:
        assert re.search(r"reg\s+\[[^\]]+\]\s+"+re.escape(name)+r"\s*=\s*\d+'d1;",source),name
    lines=source.splitlines(); result=[]; active=None; depth=0; seen=set(); labels={}; case_labels=[]
    for line in lines:
        match=re.search(r"\bcase\s*\(\s*(\w+)\s*\)",line)
        if active is None and match and match[1] in names:
            active=match[1];seen.add(active);case_labels=[];depth=1
            line=line[:match.start()]+"(* parallel_case *) case (1'b1)"+line[match.end():]
        elif active is not None:
            if re.search(r'\bcase\s*\(',line):depth+=1
            if depth==1:
                label=re.match(r"(\s*)\d+'d(\d+):(.*)",line)
                if label:
                    value=int(label[2]);assert value>0 and value & (value-1)==0
                    index=value.bit_length()-1;case_labels.append(index)
                    line=f"{label[1]}{active}[{index}]:{label[3]}"
            if depth==1 and re.match(r'\s*default:',line):
                line=re.sub(r'default:',active+'[0]:',line,count=1)
                case_labels.append(0)
            if re.search(r'\bendcase\b',line):
                depth-=1
                if depth==0:
                    assert case_labels and len(case_labels)==len(set(case_labels))
                    labels.setdefault(active,[]).append(case_labels)
                    active=None
        result.append(line)
    assert seen==set(names) and active is None,(seen,names)
    assert all(indices and len(indices)==len(set(indices)) for groups in labels.values() for indices in groups)
    return '\n'.join(result)+'\n'

if __name__=='__main__':
    import sys
    output=Path(sys.argv[sys.argv.index('--output-dir')+1])
    spec=importlib.util.spec_from_file_location('write_buffer',HERE.parent/'dram-write-buffer/generate.py')
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);base.patch_adapter(output/'write-buffer-evidence')
    patch_fsms(output/'onehot-evidence')
    runpy.run_module('litedram.gen',run_name='__main__')
    files=list(output.rglob('kc705_dram.v'));assert len(files)==1
    path=files[0];original=path.read_text()
    candidate=lower_onehot_cases(original,['builder_refresher_state'])
    evidence=output/'onehot-evidence'
    (evidence/'before-case-lowering.v').write_text(original)
    path.write_text(candidate)
    (evidence/'after-case-lowering.v').write_text(candidate)
