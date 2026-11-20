# Deeper Still Mod Kit for Blender

Make Deeper Still levels in Blender, play them in the game in one click, check
them and share them on the Steam Workshop.

- `deeperstill_modkit-<version>.zip`: the Blender add-on (Blender 5.1 or newer).
- `DeeperStill_Template.blend`: a complete level to copy and change, made from
  the game's level 8 (open it, read the `TEMPLATE_GUIDE` text in Blender's
  Text Editor).

The kit ships no game file. It reads the meshes, textures and data of **your
installed game** and keeps a local copy of them (the "extracted files").

## Install

1. Blender: *Edit > Preferences > Get Extensions > (menu) Install from Disk...*
   and choose `deeperstill_modkit-<version>.zip`.
2. In the 3D view, press **N**: the **Deeper Still** tab appears.
3. **Game** panel: *Find Game* (looks in your Steam libraries; or set the game
   folder in the add-on preferences), then *Extract Game Files*. Extract again
   after each game update (the panel tells you when).

## Make a level

- *Mod and Level* panel: *New Level* (empty level: floor, player start, NavMesh
  zone) or *New Template* (adds the template level shipped next to the kit;
  a small commented level when it is not found). Units: 1 Blender unit
  = 1 cm, Z up.
- **Scenery**: every visible mesh or curve that is not a kit object becomes a
  static mesh of the level, with a collision that blocks everything. Hidden
  objects are ignored. 3D texts are never exported (use them as notes).
- **Materials**: a Blender material becomes the game material **with the same
  name** (`Concrete`, `Concrete.001` -> the game's Concrete). *Add > Game
  Material* lists them and assigns one; *Load Game Textures* shows the game's
  textures (approximate preview). Unknown material: grey blockout, reported
  at the export.
- **Kit objects** (*Add* panel, or *Shift+A > Deeper Still*): their origin is at
  the feet for NPCs and the player start; they look along their +X axis.

| Object | Settings | In the game |
|---|---|---|
| Player Start | | where the player starts (the first one) |
| Hostile NPC | Type, Weapon (none for melee types), Hair, Behaviour (Static, Patrolling, MovingRandomly), patrol list | enemy |
| Peaceful NPC | Type, Hair, Static, Can't panic | civilian |
| Patrol Point | Stop (the NPC stops and turns to the point's +X) | point of a patrol, walked in order, in a loop |
| Ladder | Rungs (35 cm each), Two-sided | climbed from its +X side |
| Door | | swinging door: origin = hinge, leaf along +Y |
| End Portal | | 12.5 m square, 10 m deep trigger **below** its origin: entering it wins the level (put it in a pit) |
| Win Box | | closed box where the winner is moved at the end: keep it away from the level |
| Win Camera | | view of the end of the level when no NPC was killed (100° horizontal field of view) |
| NavMesh Zone | | NPCs only walk inside the zones (none: one zone around the whole level) |
| Play Area | its faces (Edit Mode) | the player is **out of bounds** where no Play Area face is above them (up to 400 m); invisible. None: one above the whole level |
| Air Vent, Tree, Throwable Object | Tree type, mesh | as in the game |

## Walls, floors and windows

Panel **Walls and Floors**. The kit builds real geometry (no modifier, no
Geometry Nodes): what you see is what the game gets.

- **Add Wall**: the selected meshes become walls (their **edges** are the
  outline, drawn from above), or a new 6 m x 4 m room at the 3D cursor. Each
  edge is extruded straight up.
- **Add Floor**: the selected meshes become floors (their **faces** are the
  outline), or a new 6 m x 4 m floor. Each face keeps its material.
- **Add Window**: a box at the 3D cursor, cut out of the walls. Its +Y axis
  goes through the wall. **Use as Opening**: any closed mesh becomes an
  opening (doorways, arches...). Openings are never exported (blue wireframe).
- **Edit Outline** (wall or floor selected): edit the outline in Edit Mode;
  the wall is built again as you go (and when its settings or an opening
  change). **Done** goes back to the wall. **Rebuild** builds the selected
  walls again (all of the scene when nothing is selected). **Freeze** turns
  a wall into an ordinary mesh.

| Object | Settings |
|---|---|
| Wall | Height; Thickness; Offset (side of the thickness: -1 on the right of each outline edge, walking along it seen from above, 1 on the left, 0 centred); Dark Base and Dark Height (the game's contact shadow: dark at the bottom of the wall, fading to white at the Dark Height, painted in the `AO` colour); Cut Openings; UV Tile (box UV projection, 0: none); Smooth Angle |
| Floor | Thickness (below the outline faces); Cut Openings (off by default); UV Tile; Smooth Angle |
| Opening | Width, Height (from its origin up), Depth (centred on its origin); Custom Shape (its own mesh); Glass Pane, Glass Offset (along its Y axis), Glass Material (empty: the game's Glass) |

Materials of a wall or floor are the material slots of its outline (*Add >
Game Material* on the wall changes both). Openings should not overlap each
other. Copies (Shift+D) get their own outline.

Hostile NPC patrols: select the NPC, *New Patrol Point* (at the 3D cursor) or
select points and *Add Selected Points*; routes are drawn in orange.

**Base level** (*Mod and Level* panel): the game level whose music, fog, sky
and post-process your level uses.

## Play, check, share

- **Mod folder**: any folder of yours, never the game folder. *Export Mod*
  writes there: `mod.json`, `levels/<Level name>.json`,
  `meshes/<Mod id>/<Level name>/*.glb`, `collision/<Mod id>/<Level name>/*.json`,
  then the game computes the level's navigation (`navmesh/<Level name>.nav`,
  10 to 30 s, no window): the NPCs move as soon as the level starts. Without
  the game, the navigation is computed when the level loads.
- **Play Here**: exports (navigation included), then starts the game with
  `--mod <mod folder> --level <Level name>`. *Start*: the scene's player start,
  or under the 3D view / 3D cursor (then a play-test copy of the mod is used).
- **Verify**: runs the game's verifier (`--mod-verifier <mod folder>`), one
  problem per line in the panel.
- **Render Preview**: `preview.png` (Workshop preview and level thumbnail)
  from the win camera.
- **Publish to Workshop**: asks for a confirmation, then runs
  `--workshop-envoyer <mod folder>`. The item is created **private**; change
  its visibility on Steam. Steam may ask you to accept the Workshop legal
  agreement.

`mod.json` (written by the export; other fields, such as the Workshop item id
written by the game, are kept):

```json
{"id": "my_first_mod", "name": "My First Mod", "version": "1.0.0", "api": 1, "type": "Level",
 "levels": [{"map": "MyLevel", "title": "My Level", "thumbnail": "preview.png"}], "requires": []}
```

## Names

Mod id and level name: letters, digits and `_`. Object names become actor and
file names: other characters become `_`, and a few words that the game uses
for its own data (such as `mesh_`, `mat_`, `Logic`) get one letter's case
changed.

## Folders of the kit

- Extracted files and the export cache: `%LOCALAPPDATA%\DeeperStillModKit`
  (Windows), `~/.local/share/DeeperStillModKit` (Linux). Delete it to start
  again.
- Add-on preferences: game folder, extracted files folder.

## For AI assistants

Read `MODDING.md` (next to this folder) first. A level exported by this kit
is plain JSON (`levels/<map>.json`: `actors`, `meshes`) and GLB files; after a
change, run `DeeperStill.exe --mod-verifier <mod folder>` and fix every line
it prints.
