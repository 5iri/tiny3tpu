"""Cycle-equivalent local boot acceptance and AXI write first-beat lookahead."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def patch_soc(source):
    spec = importlib.util.spec_from_file_location('boot_local', HERE.parent / 'boot-local-enable/prepare.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.patch_soc(source)


FIRST = '''// Exact lookahead for beat_count == 0; no extra handshake cycle.
reg main_write_first_q = 1'b1;
always @(posedge sys_clk) begin
    if (main_write_aw_valid && main_write_aw_ready)
        main_write_first_q <= main_write_aw_last || (&main_write_beat_count);
    if (sys_rst)
        main_write_first_q <= 1'b1;
end
'''


def patch_dram(source):
    old = "assign main_write_aw_first = (main_write_beat_count == 1'd0);"
    assert source.count(old) == 1
    # Refuse an upstream counter implementation that has not been proved.
    expected = ["reg     [7:0] main_write_beat_count = 8'd0;",
                "            main_write_beat_count <= 1'd0;",
                "            main_write_beat_count <= (main_write_beat_count + 1'd1);",
                "        main_write_beat_count <= 8'd0;"]
    for line in expected:
        assert source.count(line) == 1, line
    assert source.count('main_write_beat_count <=') == 3
    return source.replace(old, FIRST + 'assign main_write_aw_first = main_write_first_q;')
