"""Collapse several independently identical parallel reset stages."""
from synapse32_reset_copy_equivalence import collapse_reset_copy as collapse_one

def collapse_reset_copy(design,evidence):
    if 'replicas' not in evidence:return collapse_one(design,evidence)
    result=design
    for replica in reversed(evidence['replicas']):result=collapse_one(result,replica)
    return result
