# Changelog

One entry per version of the kit. `api` is the mod format version that the
game reads (`"api"` in `mod.json`); it changes only when the format breaks
(see "Format changes" in `MODDING.md`).

## 1.0.0 (2026-11-20)

- Mod format: `api` 1 (game 1.0, first version).
- Mod types: `Level`, `Asset Replacement`, `Gameplay Mod` (the Workshop tags).
- Game commands: `--mod`, `--mod-verifier`, `--extraire-assets`,
  `--mod-schemas`, `--bake-navmesh`, `--workshop-envoyer`, and the play test
  `--headless --mod <folder> --level <map> --autotest smoke:30`.
- JSON schemas: `mod.json`, levels, weapons, enemies, weapon and ability
  menu, dialogues.
- Examples: texture replacement, weapon tweak, mini level.
- Blender add-on `deeperstill_modkit` 1.0.0 (Blender 5.1 or newer).
