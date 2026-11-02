"""Exercise the actual tiny3tpu core, renderer, publication, and LCD scanout."""
from pathlib import Path
import json
import re
import subprocess
from assets import ROOT, generate as assets
from reference import generate


def run(command, name):
    log = ROOT / "build" / (name+".log")
    with log.open("w") as out:
        result = subprocess.run(command, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(log.read_text()[-12000:])
    return log.read_text()


def main():
    (ROOT/"build").mkdir(exist_ok=True)
    assets()
    generate()
    for name, sources in {
        "scene": ["src/scene.sv"],
        "display": ["src/framebuffer.sv", "src/scanout.sv"],
    }.items():
        run(["iverilog", "-g2012", "-s", "tb_"+name, "-o", "build/test-"+name,
             *sources, "tb/tb_"+name+".sv"], name+"-compile")
        print(run(["vvp", "build/test-"+name], name+"-test").strip())
    sources = ["src/banana_renderer.sv", "../../multi-core/tpu_core_wrapper.sv",
               "../../systolic_array/rtl/NxN_systolic_array.v", "../../systolic_array/rtl/pe.v"]
    run(["verilator", "--binary", "--timing", "--top-module", "tb_renderer", "verilator.vlt",
         "-Wno-TIMESCALEMOD", "--Mdir", "build/obj_renderer", "-o", "../test-renderer", "-j", "4",
         *sources, "tb/tb_renderer.sv"], "renderer-compile")
    log = run(["build/test-renderer"], "renderer-test")
    print(log.strip())
    frames = [{"phase": int(p), "cycles": int(c), "milliseconds": int(c)/33554.432}
              for p,c in re.findall(r"FRAME phase=(\d+) cycles=(\d+)", log)]
    (ROOT/"build/verification.json").write_text(json.dumps({
        "scope": "RTL simulation, not physical frame readback", "frames": frames,
        "coordinates_checked": 9792, "pixels_checked": 368640, "gemms": 816,
    }, indent=2)+"\n")
    # Optional visual artifact; correctness checks above need only stdlib/tools.
    try:
        from PIL import Image
        images=[Image.open(p).convert("RGB").resize((640,576),Image.Resampling.NEAREST)
                for p in sorted((ROOT/"build").glob("frame-*.ppm"))]
        images[0].save(ROOT/"build/banana-rtl.gif",save_all=True,append_images=images[1:],duration=140,loop=0)
        contact=Image.new("RGB",(640,576))
        for i,p in enumerate(sorted((ROOT/"build").glob("frame-*.ppm"))):
            contact.paste(Image.open(p),(160*(i%4),144*(i//4)))
        contact.save(ROOT/"build/preview.png")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
