"""Remove a redundant CSR read-validity gate, without changing CSR validity."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
SOURCE=ROOT.parent/'synapse32/rtl/core_modules/csr_file.v'
def patch(source):
    old='if (read_enable && csr_valid) begin'
    assert source.count(old)==1
    return source.replace(old,'if (read_enable) begin')
