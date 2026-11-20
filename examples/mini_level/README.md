# Example: mini level

Type `Level`. A copy of the first tutorial as a new level `ExampleLevel`,
played from the **Community Maps** entry of the level selection.

This repository ships no game file. To complete the example, copy from your
extracted game files (`DeeperStill.exe --extraire-assets <extracted folder>`):

| Copy this extracted file | To this path in the example |
|---|---|
| `levels/LVL_Tutorial_01.json` | `levels/ExampleLevel.json` |
| `textures/Scene/Level_MainMenu/MainMenu/LevelPreview_01.png` | `thumbnail.png` (level thumbnail) |
| `textures/Scene/Level_MainMenu/MainMenu/LevelPreview_01.png` | `preview.png` (Workshop image) |

Then, in `levels/ExampleLevel.json`, set `"name": "ExampleLevel"` and
`"package": "@/Maps/ExampleLevel"` (the file name of a level and its `name`
are the `map` declared in `mod.json`). Format: `schemas/level.schema.json`.

Check it: `DeeperStill.exe --mod-verifier <this folder>`, then play it:
`DeeperStill.exe --mod <this folder> --level ExampleLevel`.

A complete copy is in the game folder: `ModdingKit/examples/mini_level`.
