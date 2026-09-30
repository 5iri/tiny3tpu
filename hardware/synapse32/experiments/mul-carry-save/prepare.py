"""Combine registered multiply partial products with a carry-save reduction."""
from pathlib import Path
OLD='''    wire signed [35:0] middle = {{2{p01[33]}},p01} +
                                {{2{p10[33]}},p10} + {20'b0,p00[31:16]};
    wire [31:0] high_word = p11[31:0] + {{12{middle[35]}},middle[35:16]};'''
NEW='''    // Work modulo 2^48 above the unaffected low sixteen bits. Two
    // carry-save levels leave one carry-propagating adder, at the same edge.
    wire [47:0] x = {{14{p01[33]}},p01};
    wire [47:0] y = {{14{p10[33]}},p10};
    wire [47:0] z = {p11[31:0],16'b0};
    wire [47:0] w = {32'b0,p00[31:16]};
    wire [47:0] sum1 = x ^ y ^ z;
    wire [47:0] carry1 = ((x & y) | (x & z) | (y & z)) << 1;
    wire [47:0] sum2 = sum1 ^ carry1 ^ w;
    wire [47:0] carry2 = ((sum1 & carry1) | (sum1 & w) | (carry1 & w)) << 1;
    wire [47:0] combined = sum2 + carry2;'''
EXPR='low_s2 ? {middle[15:0],p00[15:0]} : high_word'
NEWEXPR='low_s2 ? {combined[15:0],p00[15:0]} : combined[47:16]'
def patch(source):
    assert source.count(OLD)==1 and source.count(EXPR)==1
    result=source.replace(OLD,NEW).replace(EXPR,NEWEXPR)
    assert result.replace(NEW,OLD).replace(NEWEXPR,EXPR)==source
    return result

def prepare(source,out):
    out.mkdir(parents=True,exist_ok=False);overlay=out/'overlay';overlay.mkdir()
    for path in source.glob('*.v'):(overlay/path.name).write_bytes(path.read_bytes())
    path=overlay/'alu.v';path.write_text(patch(path.read_text()));return overlay
