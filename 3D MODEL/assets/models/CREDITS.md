# 3D model credits

The head and every hair, facial-hair, eye, eyebrow, eyelash and glasses model
in Nishaan is built from [MakeHuman](http://www.makehumancommunity.org) assets
with [MPFB](https://extensions.blender.org/add-ons/mpfb/) for Blender. Each asset
was fitted to the same MakeHuman male base mesh, then scaled and exported into
the app's head space (Y-up, +Z = face front). The build is reproducible with
`scripts/assets/mh_build.py` and `scripts/assets/fit.py`.

**Changes made to every asset:** fitted to the base mesh, cut/transformed into
head space, materials removed (the app applies its own), and for glasses split
into `frame` / `lens_left` / `lens_right` objects.

Asset packs: <https://static.makehumancommunity.org/assets/assetpacks.html>

## Textures and morph data (CC0)

| File | Source |
|---|---|
| `skins/*.webp` | MakeHuman system skins (young / middleage / old × african / asian / caucasian × male / female), resized, slightly desaturated |
| `facial/eye_base.webp`, `facial/eye_iris_mask.webp` | MakeHuman `brown_eye` / `blue_eye` textures (iris made neutral grey so the app can tint it) |
| `hair/*.webp`, `facial/Beard*.webp`, `facial/Moustache1.webp`, `facial/eyebrows.webp`, `facial/eyelashes.webp` | Each asset's own MakeHuman texture, converted to brightness + alpha so the colour pickers still work (same licence as the model in the tables below) |
| `base/head_morphs.json`, `base/head_morphs.bin` | MakeHuman detail targets and macro (age / sex / ancestry / weight / muscle) targets, measured on `head.glb` |
| `facial/EyeLeft.glb`, `facial/EyeRight.glb` | MakeHuman `high-poly` eyes (eyeball + cornea) |

## CC0 (public domain)

| File | MakeHuman asset | Author | Pack |
|---|---|---|---|
| `base/head.glb`, `base/base_face.obj` | base mesh (head + neck, subdivided once) | MakeHuman team | MPFB |
| `facial/eyebrows.glb` | eyebrow001 | MakeHuman team | makehuman_system_assets |
| `facial/eyelashes.glb` | eyelashes01 | MakeHuman team | makehuman_system_assets |
| `hair/Hair1.glb` | short02 | MakeHuman team | makehuman_system_assets |
| `hair/Hair2.glb` | short01 | MakeHuman team | makehuman_system_assets |
| `hair/Hair3.glb` | short03 | MakeHuman team | makehuman_system_assets |
| `hair/Hair4.glb` | short04 | MakeHuman team | makehuman_system_assets |
| `hair/Hair5.glb` | culturalibre_hair_05 | culturalibre | hair01 |
| `hair/Hair7.glb` | afro01 | MakeHuman team | makehuman_system_assets |
| `hair/Hair11.glb` | bob01 | MakeHuman team | makehuman_system_assets |
| `hair/Hair12.glb` | long01 | MakeHuman team | makehuman_system_assets |
| `hair/Hair13.glb` | ponytail01 | MakeHuman team | makehuman_system_assets |
| `hair/Hair14.glb` | braid01 | MakeHuman team | makehuman_system_assets |
| `facial/Beard2.glb` | wdg_scruffy_beard | WDG | bodyparts05 |
| `facial/Beard3.glb` | rehmanpolanski_beard_viking | RehmanPolanski | bodyparts05 |
| `facial/Beard5.glb` | culturalibre_faun_beard | culturalibre | bodyparts05 |
| `facial/Beard6.glb` | grinsegold_beard_sigmund_wip | grinsegold | bodyparts05 |
| `../Glasses/Glasses_01.obj` | kwnet_at_optical_glasses | kwnet_at | glasses01 |
| `../Glasses/Glasses_03.obj` | toigo_round_glasses_leopard | MargaretToigo | glasses01 |

## CC-BY 4.0 (attribution required)

These assets are licensed under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).
Keep this section with any redistribution of the app or its models.

| File | Asset | Author | Pack |
|---|---|---|---|
| `hair/Hair6.glb` | elvs_short_side_do | Elvaerwyn | hair02 |
| `hair/Hair8.glb` | elvs_micky_afro | Elvaerwyn | hair02 |
| `hair/Hair9.glb` | elvs_braided_rows | Elvaerwyn | hair02 |
| `hair/Hair10.glb` | elvs_maxwell_hair | Elvaerwyn | hair02 |
| `facial/Beard1.glb` | grinsegold_full_beard | grinsegold | bodyparts06 |
| `facial/Beard4.glb` | elvs_scruffy_beard1 | Elvaerwyn | bodyparts06 |
| `facial/Moustache1.glb` | grinsegold_moustache | grinsegold | bodyparts06 |
| `../Glasses/glasses.obj` | elvs_ladies_sunglass1 | Elvaerwyn | glasses02 |
| `../Glasses/Glasses_04.obj` | punkduck_glasses_modern_form | punkduck | glasses02 |

## Not from MakeHuman

`face_mask/`, `../accessories/` (bandana, earrings, eyebrow ring) and
`../Hair_Previews/` are the project's own files. The hair preview clips were
re-rendered from the models above.
