"""Keep PE accumulator payload reset-free, masking it with reset ownership."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parents[3]/'systolic_array/rtl/pe.v'
GOLDEN=HERE/'pe_original.v'

def patch(source):
    assert source.count('output reg signed [CW-1:0] c')==1
    source=source.replace('output reg signed [CW-1:0] c','output wire signed [CW-1:0] c')
    source=source.replace('    always @(posedge clk or posedge rst) begin','''    reg signed [CW-1:0] c_payload;
    reg c_valid;
    wire signed [CW-1:0] feedback = c_valid ? c_payload : {CW{1'b0}};
    assign c = feedback;
    always @(posedge clk or posedge rst) begin
        if (rst) c_valid <= 1'b0;
        else c_valid <= 1'b1;
    end
    always @(posedge clk) begin
        if (clear) c_payload <= 0;
        else c_payload <= feedback + (a_in * b_in);
    end
    always @(posedge clk or posedge rst) begin''',1)
    source=source.replace('            c <= 0;\n','')
    source=source.replace('            c <= c + (a_in * b_in);\n','')
    return source

def prepare(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    source=SOURCE.read_text()
    (out/'pe.v').write_text(source if 'reg c_valid;' in source else patch(source))
