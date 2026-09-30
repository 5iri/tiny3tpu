"""Factor UART acceptance away from irrelevant external request readiness."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
NEW="    wire uart_accept = !rst && idle && req_valid && uart_address;"
def patch_soc(source):
    anchor='    wire accept = req_valid && req_ready;'
    assert source.count(anchor)==1
    source=source.replace(anchor,anchor+'\n'+NEW)
    assert source.count('accept && uart_address')==2
    return source.replace('accept && uart_address','uart_accept')
def prepare(out):
    path=Path(out)/'synapse32_dram_soc.sv'
    path.write_text(patch_soc(path.read_text()))
