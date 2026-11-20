# Deeper Still Modding Kit

Documentation, file formats, examples and the Blender add-on for making mods
for **Deeper Still** (Steam): new levels, texture and sound replacements,
gameplay tweaks. Mods are shared on the Steam Workshop and appear in the
game's **Mods** menu.

**This repository contains no game file.** Mods are made from the files of
your own installed copy of the game (see "Game files" below).

## For AI assistants

A player asked you to make or fix a Deeper Still mod. Mods are folders of
data files (JSON, images, sounds, meshes): no scripts, shaders or programs.

**Read, in this order:**

1. This README: where things are and the commands.
2. [`MODDING.md`](MODDING.md): the mod format (`mod.json`, folder layout,
   replaceable paths, units), recipes and every command.
3. [`schemas/index.json`](schemas/index.json), then the JSON schema of each
   file you write (`schemas/mod.schema.json`, `schemas/level.schema.json`,
   `schemas/weapons.schema.json`...).
4. [`examples/`](examples): one folder per kind of mod. Each has a
   `README.md` listing the game files to copy into it (this repository
   ships none). Complete, ready-to-check copies are in the installed game,
   in `ModdingKit/examples/`.
5. [`Blender/BLENDER_KIT.md`](Blender/BLENDER_KIT.md) if the player makes
   levels in Blender.

**Work loop** (run from the game folder; `DeeperStill.exe` is a windowed
program: pipe its output, as below, so that the terminal waits for it and
shows what it prints):

```powershell
# 0. Once: the game files in the mod layout, to copy and edit
.\DeeperStill.exe --extraire-assets "<extracted folder>" | Out-Host

# 1. Check the mod: fix every "error:" line, then run it again
.\DeeperStill.exe --mod-verifier "<mod folder>" | Out-Host
$LASTEXITCODE    # 0: no error (last line "... error(s) ...: OK"); 1: errors

# 2. Play it 30 seconds without a window
.\DeeperStill.exe --headless --mod "<mod folder>" --level <map> --autotest smoke:30 | Out-Host
$LASTEXITCODE    # 0: the level ran without problem ("SMOKE <map> ... OK")
```

- `<map>` is a level name without folder or extension: a level of the mod
  (`levels/<map>.json`, declared in `mod.json`) or of the game (`LVL_01` to
  `LVL_13`, `LVL_Tutorial_01`...).
- The verifier prints one problem per line,
  `error: <file>: <field>: <message>` (with "did you mean ..." for unknown
  paths), then `<n> error(s), <m> warning(s)`. `warning:` lines are advice.
- Loop on "edit, check, play" until the verifier says `0 error(s)` and the
  play test returns 0. In the play test output, look for `ERROR` and
  `panicked` lines.
- From Git Bash, run it directly: the shell waits for it
  (`./DeeperStill.exe --mod-verifier "<mod folder>"; echo $?`).
- The game also writes its log to
  `%LOCALAPPDATA%\DeeperStill\Saved\Logs\DeeperStill.log`.

**Where things are on the player's computer:**

- **Game folder**: in Steam, right-click Deeper Still, *Manage*, *Browse
  local files* (a folder of `steamapps/common` in a Steam library). It holds
  `DeeperStill.exe` and `ModdingKit/`: the same documentation as this
  repository, complete examples, and `ModdingKit/Blender/` (add-on zip,
  `BLENDER_KIT.md`, template level).
- **Template level** `DeeperStill_Template.blend`: only in the game folder,
  `ModdingKit/Blender/DeeperStill_Template.blend`. It contains game assets,
  so it is not in this repository. In Blender, *Mod and Level* panel, *New
  Template* opens it from the installed game.
- **Game files** (meshes, textures, sounds, settings tables, levels): never
  in a mod or in this repository. Extract them from the installed game with
  `--extraire-assets <folder>` (also writes `paths.txt`, the list of
  replaceable paths). The Blender add-on does the same with *Extract Game
  Files* (stored in `%LOCALAPPDATA%\DeeperStillModKit`), then *Load Game
  Textures* shows the game's textures on the materials.
- **Mod being made**: a folder of the player's own, outside the game
  folder, passed with `--mod <folder>` (repeatable; the first one has the
  highest priority). Without `--mod`, the game loads the mods of a `mods/`
  folder next to `DeeperStill.exe` (one sub-folder per mod) and the
  Workshop subscriptions; the **Mods** entry of the main menu turns them on
  or off.

## What you can make

| Type (`type` in `mod.json`) | Content | Example |
|---|---|---|
| `Asset Replacement` | images, sounds, fonts at the same paths as the game files | [`examples/texture_replacement`](examples/texture_replacement) |
| `Gameplay Mod` | settings tables in JSON (weapons, enemies, dialogues...) | [`examples/weapon_tweak`](examples/weapon_tweak) |
| `Level` | new levels (`levels/<map>.json`, meshes), played from **Community Maps** | [`examples/mini_level`](examples/mini_level) |

Mod format version: `api` **1** (see [`CHANGELOG.md`](CHANGELOG.md)).

## Install the Blender add-on

Requires **Blender 5.1** or newer.

1. Get `deeperstill_modkit-1.0.0.zip`: in the game folder,
   `ModdingKit/Blender/`, or in the *Releases* of this repository.
2. Blender: *Edit > Preferences > Get Extensions*, menu at the top right,
   *Install from Disk...*, choose the zip.
3. In the 3D view, press **N**: the **Deeper Still** tab appears.
4. *Game* panel: *Find Game* (looks in your Steam libraries), then *Extract
   Game Files*.

The add-on sources are in [`Blender/deeperstill_modkit`](Blender/deeperstill_modkit);
full guide: [`Blender/BLENDER_KIT.md`](Blender/BLENDER_KIT.md).

## Your first mod in 5 minutes (no Blender)

Double the damage of the Desert Eagle. In PowerShell, in the game folder:

```powershell
# 1. Extract the game files (once)
.\DeeperStill.exe --extraire-assets "$HOME\DeeperStillFiles" | Out-Host

# 2. Mod folder with a copy of the weapon table
$mod = "$HOME\DeeperStillMods\MyFirstMod"
New-Item -ItemType Directory -Force "$mod\datatables\WeaponSystem" | Out-Null
Copy-Item "$HOME\DeeperStillFiles\datatables\WeaponSystem\Weapon.json" "$mod\datatables\WeaponSystem\"
```

3. Open `$mod\datatables\WeaponSystem\Weapon.json`, find the row whose
   `RowName` is `Desert_Eagle` and change `"Damage": 50` to `"Damage": 100`.
4. Create `$mod\mod.json`:

   ```json
   {
     "id": "my-first-mod",
     "name": "My first mod",
     "version": "1.0.0",
     "api": 1,
     "type": "Gameplay Mod",
     "description": "Desert Eagle damage 100 instead of 50."
   }
   ```

5. Check it, then play it:

   ```powershell
   .\DeeperStill.exe --mod-verifier $mod | Out-Host
   .\DeeperStill.exe --mod $mod --level LVL_01
   ```

6. Share it: add a `preview.png` (under 1 MB), then
   `.\DeeperStill.exe --workshop-envoyer $mod | Out-Host` with Steam
   running. The Workshop item is created **private**; change its visibility
   on its Steam page.

## Your first level (Blender)

1. Install the add-on (above), *Extract Game Files*.
2. *Mod and Level* panel: *New Template* (the template level of the game)
   or *New Level* (an empty level).
3. Choose a **Mod folder** (outside the game folder), then **Play Here**:
   the add-on exports the mod and starts the game on your level.
4. **Verify**, **Render Preview**, then **Publish to Workshop**.

Details: [`Blender/BLENDER_KIT.md`](Blender/BLENDER_KIT.md), and the
"Make a level" recipe of [`MODDING.md`](MODDING.md).

## Contents of this repository

| Path | Content |
|---|---|
| [`MODDING.md`](MODDING.md) | the mod format, recipes and commands (same file as `ModdingKit/MODDING.md` in the game) |
| [`schemas/`](schemas) | JSON schemas of the formats, produced by the game (`DeeperStill.exe --mod-schemas <folder>`) |
| [`examples/`](examples) | example mods (game files to copy listed in each `README.md`) |
| [`Blender/`](Blender) | the Blender add-on sources and its guide |
| [`CHANGELOG.md`](CHANGELOG.md) | changes of the kit and of the mod format (`api`) |

The documentation, schemas, examples and add-on are copied from the game at
each update of the kit; the copies in the game folder match the game you
have installed.

## License

Code and documentation: [MIT](LICENSE). This repository contains no asset of
the game; the game's files stay under the game's license and are read from
your installed copy.
