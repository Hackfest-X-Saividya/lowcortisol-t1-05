# Rebuilding the 3D assets

The head, hair, facial hair, eyes and glasses in `assets/` are generated from
MakeHuman assets (see `assets/models/CREDITS.md`). To rebuild them:

1. Install the **MPFB** extension in Blender 4.2+ (Edit → Preferences → Get Extensions),
   or headless:
   ```bash
   blender --online-mode --command extension install mpfb --enable
   ```
2. Download the asset packs from
   <https://static.makehumancommunity.org/assets/assetpacks.html> —
   `makehuman_system_assets`, `hair01`, `hair02`, `eyebrows01`, `eyelashes01`,
   `glasses01`, `glasses02`, `bodyparts05`, `bodyparts06` — and unzip them into
   MPFB's user data folder
   (`%APPDATA%\Blender Foundation\Blender\<ver>\extensions\.user\blender_org\mpfb\data`).
3. Build (writes `<out>/models/...`, `<out>/Glasses/...`, `<out>/manifest.json`):
   ```bash
   blender -b -P scripts/assets/mh_build.py -- <out>
   ```
4. Split glasses lenses and compute calibration (`<out>/calibration.json`).
   `fit.py` remaps the landmark table of the **original** head, so pass that
   version of `OBJMorpher.js`, not the current one:
   ```bash
   git show f74a9a9:src/renderer/js/OBJMorpher.js > /tmp/OBJMorpher.orig.js
   python scripts/assets/fit.py <out> /tmp/OBJMorpher.orig.js
   ```
5. Textures and morph data:
   ```bash
   python scripts/assets/mh_textures.py "<mpfb data dir>" <out>
   python scripts/assets/pack_morphs.py <out> <out>/models/base
   ```
   Copy `<out>/models/*` (GLBs, `.webp` textures, `skins/`, `base/head_morphs.*`)
   into `assets/models/` and `<out>/Glasses/*.obj` into `assets/Glasses/`, then
   regenerate region data:
   ```bash
   python backend/analyze_mesh.py
   ```
6. If the head changed, update the constants that came from `calibration.json`:
   `OBJMorpher.LANDMARKS` / `MODEL_CONFIG.face_y_*`, the eye `BASE_*` offsets and
   scale in `EyeSystem.js`, and the brow/lash region constants in
   `HairSystem.js` / `EyeSystem.js`. Hair, beard and glasses models are
   `prefit: true`, so they need no per-model numbers.
7. Optional — re-render the hair picker clips:
   ```bash
   blender -b -P scripts/assets/render_previews.py -- . assets/Hair_Previews
   ```
