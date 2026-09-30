"""Regression: discarded net-name aliases must not hide a live carry chain."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location("offset_audit",Path(__file__).resolve().parents[1]/"tools/synapse32_offset_structure_audit_v3.py")
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
class StructureAuditTest(unittest.TestCase):
    def fixture(self,root,carry=True,dead=False):
        rtl=root/"litedram/gateware/kc705_dram.v";rtl.parent.mkdir(parents=True)
        lines=[];cells={};nets={}
        for i,(kind,channel) in enumerate([("read","ar"),("write","aw")]):
            stem="memory.main_"+kind;prefix=stem.removeprefix("memory.");base=100*i
            lines.extend([f"wire [16:0] {prefix}_offset_upper_inc = 0;",f"wire [16:0] {prefix}_offset_upper_dec = 0;"])
            nets[stem+"_offset_low"]={"bits":["0"]*13+[base+1]}
            # These old debug aliases have no drivers or consumers.
            nets[stem+"_"+channel+"_payload_addr"]={"bits":[base+80+j for j in range(30)]}
            for j,suffix in enumerate(["inc","dec"]):
                bit=base+10+j
                if not dead:
                    cells[prefix+suffix]={"type":"CARRY4" if carry else "LUT1","attributes":{"src":str(rtl.resolve())+":"+str(2*i+j+1)+".1"},"port_directions":{"I":"input","O":"output"},"connections":{"I":[base+1 if carry else base+2],"O":[bit]}}
                nets[stem+"_offset_upper_"+suffix]={"bits":[bit],"attributes":{"keep":"1"}}
        rtl.write_text("\n".join(lines));p=root/"soc.json";p.write_text(json.dumps({"modules":{"kc705_synapse32_top":{"cells":cells,"netnames":nets}}}));return p
    def test_disconnected_alias_does_not_hide_chain(self):
        with tempfile.TemporaryDirectory() as d:
            result=audit.inspect(self.fixture(Path(d)))
            self.assertTrue(all(len(v["downstream_upper_carry_cells"])==2 for v in result.values()))
    def test_live_parallel_prefix_has_no_late_dependency(self):
        with tempfile.TemporaryDirectory() as d:
            result=audit.inspect(self.fixture(Path(d),carry=False))
            self.assertTrue(all(not v["downstream_upper_carry_cells"] and all(not n["late_carry_dependency"] for n in v["parallel_alternatives"].values()) for v in result.values()))
    def test_no_live_endpoint_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(AssertionError,"No live"):
                audit.inspect(self.fixture(Path(d),dead=True))
