"""Express UART readback as disjoint masked terms to avoid a deep index mux."""
from pathlib import Path
OLD='''always @(*) begin
    read_data = 32'h0;
    if (!rst && read_enable && uart_valid) begin
        case (reg_sel)
            3'd0: read_data = dlab ? {24'h0, dll} :
                                   {24'h0, (rx_dr ? rx_fifo_data : rbr)}; // RBR/DLL
            3'd1: read_data = dlab ? {24'h0, dlh} : {24'h0, ier};
            3'd2: read_data = {24'h0, iir};
            3'd3: read_data = {24'h0, lcr};
            3'd4: read_data = 32'h0;             // MCR
            3'd5: read_data = {24'h0, lsr};      // LSR — the key one
            3'd6: read_data = 32'h0;             // MSR (no modem)
            3'd7: read_data = {24'h0, scr};      // SCR
        endcase
    end
end'''
NEW='''wire read_active = !rst && read_enable && uart_valid;
wire [7:0] read_byte =
    ({8{read_active && reg_sel==3'd0 && dlab}} & dll) |
    ({8{read_active && reg_sel==3'd0 && !dlab && rx_dr}} & rx_fifo_data) |
    ({8{read_active && reg_sel==3'd0 && !dlab && !rx_dr}} & rbr) |
    ({8{read_active && reg_sel==3'd1 && dlab}} & dlh) |
    ({8{read_active && reg_sel==3'd1 && !dlab}} & ier) |
    ({8{read_active && reg_sel==3'd2}} & iir) |
    ({8{read_active && reg_sel==3'd3}} & lcr) |
    ({8{read_active && reg_sel==3'd5}} & lsr) |
    ({8{read_active && reg_sel==3'd7}} & scr);
always @(*) read_data = {24'b0,read_byte};'''
def patch(source):
    assert source.count(OLD)==1
    result=source.replace(OLD,NEW)
    assert result.replace(NEW,OLD)==source;return result

def prepare(out,proof):
    p=Path(out)/'uart.v';proof=Path(proof)
    assert p.read_bytes()==(proof/'parent-uart.v').read_bytes()
    p.write_text(patch(p.read_text()));assert p.read_bytes()==(proof/'uart.v').read_bytes()
