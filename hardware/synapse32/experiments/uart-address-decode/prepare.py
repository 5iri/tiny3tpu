"""Factor the UART's inclusive address interval without alignment assumptions."""
from pathlib import Path

OLD = "assign uart_valid = (addr >= `UART_BASE) && (addr <= (`UART_BASE + 7*4));"
NEW = """// An aligned 32-byte region needs only upper-bit equality and a tail check.
// Retain offsets 0..28, including unaligned accesses; offsets 29..31 are invalid.
// Other base layouts retain the original inclusive range expression.
assign uart_valid = ((`UART_BASE & 32'h1f) == 0) ?
    ((addr[31:5] == (`UART_BASE >> 5)) &&
     ((addr[4:2] != 3'd7) || (addr[1:0] == 2'b0))) :
    ((addr >= `UART_BASE) && (addr <= (`UART_BASE + 7*4)));"""


def patch(source):
    assert source.count(OLD) == 1
    return source.replace(OLD, NEW)


def prepare(out):
    path = Path(out) / 'uart.v'
    path.write_text(patch(path.read_text()))
    return path
