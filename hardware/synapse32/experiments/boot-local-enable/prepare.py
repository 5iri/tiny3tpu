"""Remove external-ready decode from the provably local boot-RAM enable."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
NEW='''    // Small boot memories cannot overlap either external address region.
    // Preserve the original expression for all other parameter values.
    wire boot_accept = (BOOT_WORDS > 0 && BOOT_WORDS <= 16384) ?
        (!rst && idle && req_valid && boot_address) : (accept && boot_address);'''

def patch_soc(source):
    anchor='    wire accept = req_valid && req_ready;'
    assert source.count(anchor)==1
    old='        if (accept && boot_address) begin'
    assert source.count(old)==1
    return source.replace(anchor,anchor+'\n'+NEW).replace(old,'        if (boot_accept) begin')

def prepare(out):
    path=Path(out)/'synapse32_dram_soc.sv'
    path.write_text(patch_soc(path.read_text()))
