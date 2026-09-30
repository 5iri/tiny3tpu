"""Compute signed final divide alternatives before the quotient-bit selection."""
from pathlib import Path
OLD='''    wire [31:0] quotient_signed = quotient_negative_q ?
                                   (~quotient_next + 32'd1) : quotient_next;
    wire [31:0] remainder_signed = dividend_negative_q ?
                                    (~remainder_next[31:0] + 32'd1) :
                                    remainder_next[31:0];'''
NEW='''    // The final quotient bit chooses already-computed upper alternatives.
    // Negation of {q,b} has low bit b and upper bits b ? ~q : -q.
    wire [30:0] quotient_upper_negated = ~quotient_q[30:0] + 31'd1;
    wire [31:0] quotient_negative = {
        trial_subtract ? ~quotient_q[30:0] : quotient_upper_negated, trial_subtract};
    wire [31:0] quotient_signed = quotient_negative_q ? quotient_negative : quotient_next;
    // -(trial-divisor) == divisor-trial modulo 2^32. Compute both
    // remainder signs alongside the comparison rather than after it.
    wire [31:0] trial_negative = ~trial_remainder[31:0] + 32'd1;
    wire [31:0] reduced_negative = divisor_q - trial_remainder[31:0];
    wire [31:0] remainder_negative = trial_subtract ? reduced_negative : trial_negative;
    wire [31:0] remainder_signed = dividend_negative_q ? remainder_negative : remainder_next[31:0];'''
def patch(source):
    assert source.count(OLD)==1
    result=source.replace(OLD,NEW)
    assert result.replace(NEW,OLD)==source;return result

def prepare(source,out):
    out.mkdir(parents=True,exist_ok=False);overlay=out/'overlay';overlay.mkdir()
    for p in source.glob('*.v'):(overlay/p.name).write_bytes(p.read_bytes())
    p=overlay/'divider.v';p.write_text(patch(p.read_text()));return overlay
