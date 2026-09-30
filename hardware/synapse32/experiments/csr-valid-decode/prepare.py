"""Factor CSR address-range decoding and remove redundant read gating."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
SOURCE=ROOT.parent/'synapse32/rtl/core_modules/csr_file.v'
def patch(source):
    old='if (read_enable && csr_valid) begin'
    assert source.count(old)==1
    source=source.replace(old,'if (read_enable) begin')
    start=source.index("                       (csr_addr >= 12'hB03")
    end=source.index(';',start)+1
    original=source[start:end]
    assert original.count('csr_addr >=')==3 and original.count('csr_addr <=')==3
    replacement="""                       // B03..B1F, B83..B9F, and 323..33F share the low range.
                       ((((csr_addr[11:8] == 4'hB) && (csr_addr[6:5] == 2'b00)) ||
                          (csr_addr[11:5] == 7'h19)) &&
                         ((|csr_addr[4:2]) || (&csr_addr[1:0])));"""
    return source[:start]+replacement+source[end:]
