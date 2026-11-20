# Modding Deeper Still

A mod is a folder of data files that the game reads **before** its own
files. You can replace textures, sounds and fonts, change game settings
(weapons, enemies…), and add new levels. Mods are shared on the Steam
Workshop. Mods contain **data only**: no scripts, shaders or programs.

Format version (`api` in `mod.json`): **1**.

## If you are an AI assistant

1. Read this file, then the schemas in `schemas/` (`schemas/index.json`
   tells which schema applies to which file).
2. Get the original game files to copy from:
   `DeeperStill.exe --extraire-assets <folder>` (writes every game file in
   the mod layout, plus `paths.txt`, the list of replaceable paths).
3. Write the mod folder (start from one of `examples/`).
4. Check it: `DeeperStill.exe --mod-verifier <mod folder>`. Fix every
   `error:` line (one problem per line: `error: <file>: <field>: <message>`;
   exit code 1 while errors remain). `warning:` lines are advice.
5. Try it without a window:
   `DeeperStill.exe --headless --mod <mod folder> --level <map> --autotest smoke:30`
   (exit code 0 = the level ran 30 seconds without problem; read the
   output for `ERROR`/`panicked` lines).
6. Loop on 3-5 until the verifier says `0 error(s)` and the test passes.

`DeeperStill.exe` is in the game folder (Steam: right click on the game,
Manage, Browse local files). Run commands from a terminal in that folder.
It is a windowed program: in PowerShell, pipe its output
(`.\DeeperStill.exe --mod-verifier <mod folder> | Out-Host`, then
`$LASTEXITCODE`), otherwise the terminal does not wait for it and the exit
code is lost. Git Bash waits by itself.

## Folder layout

```
MyMod/
  mod.json          description (required)
  preview.png       Workshop image (optional, PNG, under 1 MB)
  textures/...      files at the same paths as in the game
  datatables/...
  levels/MyLevel.json
  navmesh/MyLevel.nav   navigation of the level (optional, made by the game)
```

Every file except `mod.json`, `preview.png` and documentation (`*.md`,
`README*`, `LICENSE*`) is game content. **A file replaces the game file
with the same path** (letter case ignored). Paths are those of
`--extraire-assets` / `paths.txt` (example: `datatables/WeaponSystem/Weapon.json`,
`textures/UI/Duo/Duo_Off.png`, `levels/LVL_01.json`). A file whose path is
not a game file is a **new** file: a level (`levels/<map>.json`), or a file
used by your JSON files (mesh, texture…). The verifier reports any other
unknown path, with the closest game path ("did you mean…").

Allowed files: images (`.png`, `.jpg`, `.dds`, `.ktx2`), sounds (`.wav`,
`.ogg`, `.flac`, `.mp3`), fonts (`.ttf`, `.otf`), data (`.json`, `.glb`,
`.nav`, `.txt`, `.csv`). Code files (`.wgsl` shaders, `.exe`, `.dll`,
scripts…) make the whole mod refused. Other files are ignored. Symbolic
links are refused.

## mod.json

```json
{
  "id": "my-mod",
  "name": "My mod",
  "version": "1.0.0",
  "api": 1,
  "type": "Level",
  "levels": [{ "map": "MyLevel", "title": "My level", "thumbnail": "thumbnail.png" }],
  "requires": [],
  "description": "Shown on the Workshop."
}
```

- `id`: unique, lowercase letters, digits, `_`, `-`, `.` (1-64).
- `type`: exactly one of the Workshop tags `Level`, `Asset Replacement`,
  `Gameplay Mod`.
- `levels`: levels listed in the **Community Maps** entry of the level selection
  (`map` = file `levels/<map>.json` without extension).
- `requires`: ids of other mods that must be active (optional).
- `workshop_id`: written by the game after the first upload; do not edit.

Schema: `schemas/mod.schema.json`.

### Types, achievements and progression

- `Asset Replacement`: only images, sounds and fonts. Achievements, level
  timer and progression are kept.
- `Level` and `Gameplay Mod`: no achievements; progression and timer are
  kept (same save as without mods). Levels of a mod never change the
  progression. Hardcore mode stays available.
- The game decides from the files really present: an `Asset Replacement`
  mod with any data file (JSON, GLB…) is treated as a `Gameplay Mod`
  (warning from the verifier; the Workshop tag follows).

## JSON files

Copy the game file from `--extraire-assets` and change values: the game
reads the whole file (a field you remove takes its default value). Keep
the style of references used in the game files, for example object paths
`@/Scene/...` and mesh paths `meshes/user/...`. Files you add are referenced
by their path in your mod (example: `"mesh": "meshes/MyMod/Rock.glb"`).
The verifier checks the JSON syntax, the known formats (levels, settings
tables: see `schemas/`) and broken references.

Settings tables (one row per entry, `RowName` = name of the row):

| File | Schema | Content |
|---|---|---|
| `datatables/WeaponSystem/Weapon.json` | `weapons.schema.json` | damage, fire rate, magazine, recoil… |
| `datatables/Characters/Enemies.json` | `enemies.schema.json` | enemy health, speeds… |
| `datatables/UI/Menu/WeaponAbilityButton.json` | `weapon_ability_buttons.schema.json` | weapon and ability menu |
| `datatables/Dialogues/**` | `dialogues.schema.json` | dialogue lines |

Units are those of the game: centimeters, degrees, seconds.

## Recipes

**Replace a texture.** Find the image in the extracted files, edit it,
save it at the same path in your mod (same format; the verifier warns if
the size differs). Type `Asset Replacement`. Example:
`examples/texture_replacement`.

**Change the damage of a weapon.** Copy
`datatables/WeaponSystem/Weapon.json` into your mod, change `Damage` in the
row of the weapon. Type `Gameplay Mod`. Example: `examples/weapon_tweak`.

**Make a level.** The Blender kit (`Blender/BLENDER_KIT.md` next to this
file) exports a level folder in this format. By hand: write
`levels/MyLevel.json` (schema `schemas/level.schema.json`: static meshes
and actors; start from an extracted level), declare it in `mod.json`
(`levels`), type `Level`. Play it from the main menu (level selection,
**Community Maps**) or with `--mod <folder> --level MyLevel`. Example:
`examples/mini_level`. The end of a Workshop level goes back to the main
menu.

**Navigation of a level (NPCs).** Without it, the game computes the
navigation of the level when it loads (10 to 30 seconds during which the
NPCs wait). Compute it once and ship it in the mod:
`DeeperStill.exe --headless --mod <folder> --bake-navmesh [--levels MyLevel]`
writes `navmesh/<map>.nav` in the mod folder for each level of `mod.json`
(the Blender kit does it at each export). Run it again after changing the
level: an out-of-date file is ignored (the game computes the navigation
again when the level loads).

**Out of bounds.** The player is out of bounds (screen effect) when no
out-of-bounds mesh is above them: the game traces 400 m straight up on the
`OutOfBounds` collision channel. Add a hidden static mesh whose `body`
blocks only `OutOfBounds` (copy the `OutOfBounds` actor of an extracted
level, for example `levels/LVL_08.json`) over the playable area; without
any, the player is out of bounds everywhere. The Blender kit exports its
**Play Area** objects this way (one above the whole level when there is
none).

## Commands

| Command | Use |
|---|---|
| `--mod <folder>` | load a mod (repeatable; first = highest priority); combine with `--level <map>` |
| `--mod-verifier <folder>` | check a mod (exit code 1 on error) |
| `--extraire-assets <folder>` | extract the game files in the mod layout (+ `paths.txt`, `reserved_words.txt`) |
| `--headless --mod <folder> --level <map> --autotest smoke:30` | play 30 seconds without a window |
| `--headless --mod <folder> --bake-navmesh [--levels <map>]` | compute the navigation of the mod's levels (`navmesh/<map>.nav`) |
| `--workshop-envoyer <folder> [--note "text"]` | upload to the Workshop (Steam must be running) |

Without `--mod`, the game loads the mods of the `mods/` folder next to
`DeeperStill.exe` (one sub-folder per mod) and your Workshop subscriptions.
The **Mods** entry of the main menu turns them on or off and sets their
order.

## Workshop

`--workshop-envoyer` checks the mod (no error allowed), creates the item
on the first upload (**private**; the id is written in `mod.json`), then
uploads the folder, `preview.png`, title, description and type tag. Change
the visibility on the item page. If Steam asks for it, accept the
Workshop agreement:
https://steamcommunity.com/sharedfiles/workshoplegalagreement

## Duo

Both players must use the same mods. A guest who misses Workshop mods of
the host subscribes to them automatically, then uses the host's mods in
the same order; mods that are not on the Workshop prevent joining.

## Format changes

`api` changes only when the format breaks; this section lists the changes.

- `api` 1 (game 1.0): first version.
