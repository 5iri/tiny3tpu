"""Remove reset from UART state-control inputs, preserving unreset payload/read gating."""
import re
from pathlib import Path

def gate_reference(source):
    # Model the exact parent integration: both UART enables are masked by rst.
    result=source
    for signal in ('write_enable','read_enable'):
        result=re.sub(r'\b'+signal+r'\b',signal+'_gated',result)
        result=result.replace('wire        '+signal+'_gated,','wire        '+signal+',',1)
    marker='wire [2:0] reg_sel = addr[4:2];'
    assert marker in result
    return result.replace(marker,'wire write_enable_gated = write_enable && !rst;\nwire read_enable_gated = read_enable && !rst;\n'+marker,1)

def patch_uart(source):
    result=source
    old="    if(write_enable && uart_valid && reg_sel==3'd0 && !dlab && fifo_enabled && !tx_fifo_full)"
    assert result.count(old)==1
    result=result.replace(old,old.replace('if(write_enable','if(!rst && write_enable'),1)
    old="""    if(rx_state==RX_STOP && rx_baud_counter==0 && rx && !rx_fifo_clear_request &&
       (!rx_fifo_full || rx_fifo_pop_request))"""
    new="""    if(rx_state==RX_STOP && rx_baud_counter==0 && rx && !(rx_fifo_clear_request && !rst) &&
       (!rx_fifo_full || (rx_fifo_pop_request && !rst)))"""
    assert result.count(old)==1;result=result.replace(old,new,1)
    old='    if (read_enable && uart_valid) begin'
    assert result.count(old)==1
    result=result.replace(old,'    if (!rst && read_enable && uart_valid) begin',1)
    return result

def patch_soc(source):
    old='    wire uart_accept = !rst && idle && req_valid && uart_address;'
    new='    wire uart_accept = idle && req_valid && uart_address;'
    assert source.count(old)==1
    assert source.count('uart_accept')==3
    return source.replace(old,new,1)

def prepare(out,proof):
    out=Path(out);proof=Path(proof)
    for name,patch in [('uart.v',patch_uart),('synapse32_dram_soc.sv',patch_soc)]:
        path=out/name
        assert path.read_bytes()==(proof/('parent-'+name)).read_bytes(),name
        path.write_text(patch(path.read_text()))
        assert path.read_bytes()==(proof/name).read_bytes(),name
