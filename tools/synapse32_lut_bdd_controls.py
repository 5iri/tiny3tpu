"""Cross-check exact BDD composition against exhaustive small-network tables."""
import argparse,json,random
from pathlib import Path
from synapse32_lut_bdd_equivalence import compare
from synapse32_packed_counter_encoding import evaluate,logical
from synapse32_packed_selector_patch_v4 import packed
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists()
r=random.Random(20260913);cases=100
for case in range(cases):
    cuts=list(range(10,16));available=cuts.copy();cells={}
    for i in range(8):
        width=r.randrange(1,7);inputs=[r.choice(available) for _ in range(width)];bit=100+i
        cells[str(i)]=packed(inputs,bit,r.getrandbits(1<<width));available.append(bit)
    truth=0
    for word in range(64):
        values={b:(word>>i)&1 for i,b in enumerate(cuts)}
        for c in cells.values():values[logical(c)[1]['O']]=evaluate(c,values)
        truth|=values[107]<<word
    compare(cells,{'table':packed(cuts,107,truth)},cuts,[107])
    try:compare(cells,{'bad':packed(cuts,107,truth^1)},cuts,[107])
    except AssertionError as exc:assert str(exc)=='BDD equivalence failed'
    else:raise AssertionError('accepted non-equivalent network')
record=dict(passed=True,exhaustively_cross_checked_networks=cases,inputs_per_network=6,luts_per_network=8,corrupted_tables_rejected=cases,seed=20260913,sha256={str(q.resolve()):digest(q) for q in [Path(__file__),Path(__file__).with_name('synapse32_lut_bdd_equivalence.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py')]})
a.out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
