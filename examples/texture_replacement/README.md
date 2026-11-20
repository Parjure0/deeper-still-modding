# Example: texture replacement

Type `Asset Replacement`. Replaces the image of the Duo button (bottom left
of the main menu) with its "connected" image.

This repository ships no game file. To complete the example, copy from your
extracted game files (`DeeperStill.exe --extraire-assets <extracted folder>`):

| Copy this extracted file | To this path in the example |
|---|---|
| `textures/UI/Duo/Duo_On.png` | `textures/UI/Duo/Duo_Off.png` |
| `textures/UI/Duo/Duo_On.png` | `preview.png` (Workshop image) |

Then check it: `DeeperStill.exe --mod-verifier <this folder>`.

A complete copy is in the game folder: `ModdingKit/examples/texture_replacement`.
