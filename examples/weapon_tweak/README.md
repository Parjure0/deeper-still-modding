# Example: weapon tweak

Type `Gameplay Mod`. Desert Eagle damage 100 instead of 50.

This repository ships no game file. To complete the example, copy from your
extracted game files (`DeeperStill.exe --extraire-assets <extracted folder>`):

| Copy this extracted file | To this path in the example |
|---|---|
| `datatables/WeaponSystem/Weapon.json` | `datatables/WeaponSystem/Weapon.json` |

Then, in the copy, find the row whose `RowName` is `Desert_Eagle` and change
`"Damage": 50` to `"Damage": 100`. Keep every other row: the game reads the
whole table (a row you remove is a weapon removed). Format:
`schemas/weapons.schema.json`.

Check it: `DeeperStill.exe --mod-verifier <this folder>`, then play it:
`DeeperStill.exe --mod <this folder> --level LVL_01`.

A complete copy is in the game folder: `ModdingKit/examples/weapon_tweak`.
