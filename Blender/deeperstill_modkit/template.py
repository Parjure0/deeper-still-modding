"""Level scenes made by code: empty level and commented template level.

The kit's main template is the level shipped with the game
(ModdingKit/Blender/DeeperStill_Template.blend, made from the game's level
8); the small level below is used when it is not found.

The template is a small complete level: player start, floor and walls,
NPCs with patrols, a ladder, a door, the end portal (win condition: the
level is won when the player falls into the portal pit; the game then shows
its win menu, which leads back to the menu). Scenery: boxes made here, with
game materials by name. Notes (3D texts and the `TEMPLATE_GUIDE` text) are
not exported.
"""

import math

import bpy

from . import actors

GUIDE = "TEMPLATE_GUIDE"
SHIPPED_FILE = "DeeperStill_Template.blend"   # next to the add-on in the game's ModdingKit/Blender
SHIPPED_SCENE = "Template"
NOTES = "Notes (not exported)"
TILE = 400.0  # UV: one unit every 4 m

GUIDE_TEXT = """DEEPER STILL - TEMPLATE LEVEL
=============================

A small complete level to copy and change. Units: 1 Blender unit = 1 cm
(scene unit scale 0.01), Z up. The texts floating in the 3D view and this
guide are notes: they are never exported.

HOW TO PLAY IT
1. Deeper Still panel (N key in the 3D view) > Game: Find Game, then
   Extract Game Files (once, and after each game update).
2. Mod and Level: choose a Mod folder (any empty folder, never the game
   folder), a Mod id and a Level name.
3. Play and Publish: Play Here. Verify checks the mod with the game's own
   verifier. Publish to Workshop asks for a confirmation first.

WHAT IS IN THE SCENE
- Scenery (collection Scenery): every visible mesh that is not a kit object
  becomes a static mesh of the level, with a collision that blocks
  everything. A Blender material becomes the game material of the same
  name (TutorialWall, TutorialSurface...): Add > Game Material lists them.
- Room A (start): Player Start, a peaceful NPC, a throwable wooden box.
- Door between rooms A and B: the game's swinging door (pushed open by the
  player). Its origin is the hinge; the leaf goes along its +Y axis.
- Room B (guards): two hostile NPCs patrolling (their routes are drawn in
  orange: select an NPC to see its patrol list), a platform with a ladder
  (10 rungs = 3.5 m, climbed from its +X side) and a static guard on it.
- Room C (exit): the End Portal over a pit. The portal is a 12.5 m square,
  10 m deep trigger below its origin: falling into it wins the level, the
  game shows its win menu, then goes back to the menu.
- NavMesh zone (wire box): NPCs only walk inside the NavMesh zones.
- Win Camera: view of the end of the level when no NPC was killed.
- Win Box: closed box where the winner is moved at the end; keep it away
  from the level.

RULES
- Names of objects: letters, digits and _ are kept, the rest becomes _.
- Kit objects (Add panel): their origin is at the feet for NPCs and the
  player start; they look along their +X axis.
- Base level (Mod and Level panel): the game level whose music, fog, sky
  and post-process the level uses.
"""


def shipped_template():
    """Template level shipped with the installed game (ModdingKit/Blender), or None."""
    import os
    from . import kit
    exe, _how = kit.game_exe()
    if exe is None:
        return None
    p = os.path.join(os.path.dirname(exe), "ModdingKit", "Blender", SHIPPED_FILE)
    return p if os.path.isfile(p) else None


def setup_scene(scene):
    """Units like the game (1 unit = 1 cm)."""
    us = scene.unit_settings
    us.system = "METRIC"
    us.scale_length = 0.01
    us.length_unit = "CENTIMETERS"
    scene.dsmk.map_name = "".join(c for c in scene.name if c.isalnum() or c == "_") or "MyLevel"


def _collection(scene, name):
    c = bpy.data.collections.get(name)
    if c is None or c.name not in scene.collection.children:
        c = bpy.data.collections.new(name)
        scene.collection.children.link(c)
    return c


def material(name, color):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.diffuse_color = color
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = color
    return m


def box(coll, name, mn, mx, mat):
    """Box object from min to max corner (cm), origin at its centre."""
    c = [(a + b) / 2.0 for a, b in zip(mn, mx)]
    h = [(b - a) / 2.0 for a, b in zip(mn, mx)]
    verts = [(sx * h[0], sy * h[1], sz * h[2]) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    uv = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        n = poly.normal
        axis = max(range(3), key=lambda i: abs(n[i]))
        a, b = [i for i in range(3) if i != axis]
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = ((co[a] + c[a]) / TILE, (co[b] + c[b]) / TILE)
    me.materials.append(mat)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = c
    coll.objects.link(ob)
    return ob


def note(coll, text, location, size=45.0):
    """3D text (note, never exported)."""
    cu = bpy.data.curves.new(f"Note_{text[:20]}", "FONT")
    cu.body = text
    cu.size = size
    cu.align_x = "CENTER"
    ob = bpy.data.objects.new(f"Note_{text[:20]}", cu)
    ob.location = location
    ob.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    ob.hide_render = True
    coll.objects.link(ob)
    return ob


def _actor(scene, kind, loc, yaw_deg=0.0, name=None, **props):
    o = actors.create(scene, kind, loc, name)
    o.rotation_euler = (0.0, 0.0, math.radians(yaw_deg))
    for k, v in props.items():
        setattr(o.dsmk, k, v)
    return o


def build_empty(scene):
    """Empty level: units, a 20 m floor, a player start, a NavMesh zone."""
    setup_scene(scene)
    coll = _collection(scene, f"Scenery_{scene.name}")
    box(coll, "Floor", (-1000, -1000, -50), (1000, 1000, 0), material("TutorialSurface", (0.35, 0.33, 0.30, 1)))
    _actor(scene, "PLAYERSTART", (0.0, 0.0, 0.0))
    z = _actor(scene, "NAVMESH", (0.0, 0.0, 200.0))
    z.scale = (10.5, 10.5, 4.0)


def build_template(scene):
    """Commented template level (see GUIDE_TEXT)."""
    setup_scene(scene)
    s = scene.dsmk
    s.map_name, s.level_title = "TemplateLevel", "Template Level"
    s.mod_id, s.mod_name, s.base_level = "template_mod", "Template Mod", "LVL_03"
    sc = _collection(scene, f"Scenery_{scene.name}")
    notes = _collection(scene, NOTES)
    floor = material("TutorialSurface", (0.35, 0.33, 0.30, 1))
    wall = material("TutorialWall", (0.60, 0.58, 0.55, 1))
    plat = material("TutorialSurfaceBrown", (0.30, 0.20, 0.12, 1))
    dark = material("TutorialBlack_02", (0.03, 0.03, 0.03, 1))

    X0, X1, Y0, Y1, H, T = -2000.0, 3200.0, -1000.0, 1000.0, 500.0, 40.0
    # Floor of rooms A and B, floor of room C around the pit.
    PX0, PX1, PY0, PY1, PZ = 1725.0, 2975.0, -625.0, 625.0, -1100.0
    box(sc, "Floor_RoomsAB", (X0, Y0, -50), (1500, Y1, 0), floor)
    box(sc, "Floor_C_West", (1500, Y0, -50), (PX0, Y1, 0), floor)
    box(sc, "Floor_C_East", (PX1, Y0, -50), (X1, Y1, 0), floor)
    box(sc, "Floor_C_North", (PX0, PY1, -50), (PX1, Y1, 0), floor)
    box(sc, "Floor_C_South", (PX0, Y0, -50), (PX1, PY0, 0), floor)
    # Pit under the end portal.
    box(sc, "Pit_Bottom", (PX0, PY0, PZ - 50), (PX1, PY1, PZ), dark)
    box(sc, "Pit_WallWest", (PX0 - T, PY0, PZ), (PX0, PY1, -50), dark)
    box(sc, "Pit_WallEast", (PX1, PY0, PZ), (PX1 + T, PY1, -50), dark)
    box(sc, "Pit_WallNorth", (PX0 - T, PY1, PZ), (PX1 + T, PY1 + T, -50), dark)
    box(sc, "Pit_WallSouth", (PX0 - T, PY0 - T, PZ), (PX1 + T, PY0, -50), dark)
    # Outer walls.
    box(sc, "Wall_North", (X0 - T, Y1, 0), (X1 + T, Y1 + T, H), wall)
    box(sc, "Wall_South", (X0 - T, Y0 - T, 0), (X1 + T, Y0, H), wall)
    box(sc, "Wall_West", (X0 - T, Y0, 0), (X0, Y1, H), wall)
    box(sc, "Wall_East", (X1, Y0, 0), (X1 + T, Y1, H), wall)
    # Wall A | B with a doorway (120 cm wide, 230 cm high) for the door.
    box(sc, "WallAB_South", (-520, Y0, 0), (-480, -60, H), wall)
    box(sc, "WallAB_North", (-520, 60, 0), (-480, Y1, H), wall)
    box(sc, "WallAB_Lintel", (-520, -60, 230), (-480, 60, H), wall)
    # Wall B | C with an opening (300 cm wide).
    box(sc, "WallBC_South", (1480, Y0, 0), (1520, -150, H), wall)
    box(sc, "WallBC_North", (1480, 150, 0), (1520, Y1, H), wall)
    box(sc, "WallBC_Lintel", (1480, -150, 300), (1520, 150, H), wall)
    # Platform of room B (top at 350 cm = 10 rungs of 35 cm).
    box(sc, "Platform", (1000, 500, 0), (1460, 980, 350), plat)

    # Room A: start.
    _actor(scene, "PLAYERSTART", (-1700.0, 0.0, 0.0), 0.0)
    _actor(scene, "PEACEFUL", (-1600.0, 700.0, 0.0), -90.0, peaceful_type="Woman", start_static=True)
    _actor(scene, "THROWABLE", (-1000.0, -600.0, 0.0), 20.0)
    # Door: hinge on the south side of the doorway, leaf along +Y.
    _actor(scene, "DOOR", (-500.0, -55.0, 0.0), 0.0)
    # Room B: guards.
    pts = [_actor(scene, "PATROL", p, yaw) for p, yaw in
           (((-200.0, -700.0, 0.0), 0.0), ((800.0, -700.0, 0.0), 90.0), ((800.0, -100.0, 0.0), 180.0),
            ((-200.0, -100.0, 0.0), -90.0))]
    g0 = _actor(scene, "HOSTILE", (-200.0, -400.0, 0.0), 0.0, state="NewEnumerator1")
    for p in pts:
        g0.dsmk.patrol.add().target = p
    pts1 = [_actor(scene, "PATROL", (-150.0, 350.0, 0.0), 0.0), _actor(scene, "PATROL", (750.0, 350.0, 0.0), 180.0)]
    pts1[0].dsmk.stop = False
    pts1[1].dsmk.stop = False
    g1 = _actor(scene, "HOSTILE", (300.0, 350.0, 0.0), 0.0, enemy="NewEnumerator8", weapon="NewEnumerator3",
                state="NewEnumerator1")
    for p in pts1:
        g1.dsmk.patrol.add().target = p
    _actor(scene, "LADDER", (995.0, 740.0, 0.0), 180.0, ladder_count=10)
    _actor(scene, "HOSTILE", (1230.0, 740.0, 350.0), 180.0, enemy="NewEnumerator1", weapon="NewEnumerator0")
    # Room C: exit.
    _actor(scene, "END_PORTAL", ((PX0 + PX1) / 2.0, 0.0, 0.0), 0.0)
    cam = _actor(scene, "WINVIEW", (1800.0, -900.0, 450.0))
    cam.rotation_euler = (math.radians(70.0), 0.0, math.radians(-30.0))
    _actor(scene, "WON_BOX", (0.0, -6000.0, -3000.0), 0.0)
    z = _actor(scene, "NAVMESH", ((X0 + X1) / 2.0, 0.0, 300.0))
    z.scale = ((X1 - X0) / 200.0 + 0.5, (Y1 - Y0) / 200.0 + 0.5, 4.0)

    # Notes.
    note(notes, "ROOM A - START\nPlayer Start (feet at the origin, looks along +X)", (-1700, 0, 350))
    note(notes, "Peaceful NPC (static)", (-1600, 700, 260))
    note(notes, "Throwable box: pick it up and throw it", (-1000, -600, 200))
    note(notes, "DOOR: origin = hinge,\nleaf along +Y. Pushed open by the player", (-500, -150, 330))
    note(notes, "ROOM B - GUARDS\nPatrol: points walked in order, in a loop\n(red point: stops and turns)", (300, -400, 330))
    note(notes, "Ladder: 10 rungs = 3.5 m,\nclimbed from its +X side", (900, 740, 420))
    note(notes, "Static guard on the platform", (1230, 740, 620))
    note(notes, "ROOM C - EXIT\nEND PORTAL: fall into the pit to win.\nThe win menu leads back to the menu", (2350, 0, 300))
    note(notes, "Win Box (keep it away from the level)", (0, -6000, -2500))

    txt = bpy.data.texts.get(GUIDE) or bpy.data.texts.new(GUIDE)
    txt.clear()
    txt.write(GUIDE_TEXT)
    return scene
