"""Preserve zero-after-reset register reads with ownership bits instead of payload reset."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
SOURCE=ROOT.parent/'synapse32/rtl/core_modules/registerfile.v'

def patch(source):
    start=source.index('    integer i;');end=source.index('    // Combinational read',start)
    source=source[:start]+"    reg [31:0] written = 32'b0;\n\n"+source[end:]
    for port in ['rs1','rs2']:
        old=f'{port}_value = register_file[{port}];'
        assert source.count(old)==1
        source=source.replace(old,f"{port}_value = written[{port}] ? register_file[{port}] : 32'b0;")
    start=source.index('    // Synchronous write with reset');end=source.index('\nendmodule',start)
    source=source[:start]+'''    // Reset clears ownership. Unowned payload is never observable.
    always @(posedge clk or posedge rst) begin
        if (rst) written <= 32'b0;
        else if (wr_en && rd != 5'b0) written[rd] <= 1'b1;
    end
    always @(posedge clk) begin
        if (wr_en && rd != 5'b0) register_file[rd] <= rd_value;
    end
'''+source[end:]
    return source
