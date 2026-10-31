# Shared banana scene resources

The KC705 HDMI targets use this static 204-vertex mesh, rotation ROMs, scalar
asset generator, font, scene controller, and button synchronizer. These shared
resources are independent of the Chromatic board target, which is maintained
on `feat/modretro-banana`.

The mesh is derived from the pinned jaxsim source recorded in `assets/mesh.json`.
The font and board-layer helpers retain the ModRetro-derived GPL-3.0 license in
[reference/MODRETRO-LICENSE.txt](reference/MODRETRO-LICENSE.txt).

Run `python3 tools/assets.py` here to regenerate and verify the scene ROMs.
