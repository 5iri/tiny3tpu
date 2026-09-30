"""Track UART baud-counter zero flags on their original update edges."""
from pathlib import Path
import re

def patch(source):
    result = source
    edits = []
    for counter, flag in [('baud_counter','baud_zero'), ('rx_baud_counter','rx_baud_zero')]:
        decl = f'reg [15:0] {counter};'
        newdecl = decl+f'\nreg {flag};'
        assert result.count(decl) == 1
        result = result.replace(decl,newdecl); edits.append((decl,newdecl))
        pattern = re.compile(r'^(\s*)'+counter+r'\s*(<=|=)\s*([^;]+);$', re.M)
        assignments = list(pattern.finditer(result))
        assert len(assignments) == (4 if counter=='baud_counter' else 8), counter
        for match in reversed(assignments):
            expr = match[3].strip()
            if expr == "16'd0": test = "1'b1"
            elif expr == "16'd1": test = "1'b0"
            elif expr == "baud_div": test = "baud_div == 16'd0"
            elif expr == "{1'b0, baud_div[15:1]}": test = "baud_div[15:1] == 15'd0"
            elif expr == counter+" - 1'b1": test = counter+" == 16'd1"
            else: raise AssertionError(expr)
            old = match[0]; new = old+match[1]+flag+' '+match[2]+' '+test+';'
            # Whitespace group includes a preceding newline for these lines.
            if not match[1].startswith('\n'): new = old+'\n'+match[1]+flag+' '+match[2]+' '+test+';'
            result = result[:match.start()]+new+result[match.end():]
            edits.append((old,new))
        for old,new,count in [(counter+'==0',flag,1 if counter=='baud_counter' else 2),
                              (counter+' > 0','!'+flag,1 if counter=='baud_counter' else 3)]:
            # Word boundary keeps baud_counter from matching rx_baud_counter.
            pattern = r'\b'+re.escape(old)
            result,n = re.subn(pattern,new,result)
            assert n == count,(old,n)
    # Verify that only declarations, mirrored assignments and zero tests changed.
    inverse=result
    for counter,flag in [('rx_baud_counter','rx_baud_zero'),('baud_counter','baud_zero')]:
        inverse=inverse.replace('!'+flag,counter+' > 0')
        inverse=re.sub(r'\b'+flag+r'(?= &&)',counter+'==0',inverse)
    for old,new in reversed(edits):
        assert new in inverse,(old,new)
        inverse=inverse.replace(new,old,1)
    assert inverse == source
    return result

def prepare(out):
    path=Path(out)/'uart.v';path.write_text(patch(path.read_text()))
