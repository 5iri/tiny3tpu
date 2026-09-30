"""Use an exact prefix decode for the current 64 KiB boot memory."""
from pathlib import Path
OLD = """    wire boot_address = req_addr>=32'h80000000 &&
        (req_addr-32'h80000000)<BOOT_WORDS*4;"""
NEW = """    wire boot_address = (BOOT_WORDS == 16384) ?
        (req_addr[31:16] == 16'h8000) :
        (req_addr>=32'h80000000 && (req_addr-32'h80000000)<BOOT_WORDS*4);"""


def patch(source):
    assert source.count(OLD) == 1
    result = source.replace(OLD, NEW)
    assert result.replace(NEW, OLD) == source
    return result


def prepare(out):
    path = Path(out)/'synapse32_dram_soc.sv'
    path.write_text(patch(path.read_text()))
