"""Kit objects of a scene (player start, NPCs, patrol points...): creation and export.

Each kit object is an Empty (a camera for the win camera, a wire cube for a
NavMesh zone, a wire mesh for a play area) with its settings in `Object.dsmk`. The export gives, for each
object, its pose in the level JSON frame and the properties of the game
actor (shipped names, only the values that differ from the game's defaults).
"""

import re

import bpy
from mathutils import Vector

from . import convert, display
from . import gamedata as gd
from .props import KIND_CLASS, NAME_PREFIX

COLLECTION = {"PLAYERSTART": "PlayerStart", "HOSTILE": "NPC_Hostile", "PEACEFUL": "NPC_Peaceful",
              "PATROL": "NPC_PatrolPoints", "LADDER": "Ladders", "AIRVENT": "AirVents", "TREE": "Trees",
              "THROWABLE": "Throwables", "DOOR": "Doors", "END_PORTAL": "EndPortal", "WON_BOX": "EndPortal",
              "NAVMESH": "NavMesh", "WINVIEW": "EndPortal", "PLAY_AREA": "PlayArea"}
EXPORT_KEY = {"PATROL": "patrolling_locations", "PEACEFUL": "peaceful", "HOSTILE": "hostile",
              "PLAYERSTART": "player_starts", "TREE": "trees", "LADDER": "ladders", "AIRVENT": "air_vents",
              "THROWABLE": "throwables", "DOOR": "prefabs", "END_PORTAL": "prefabs", "WON_BOX": "prefabs"}
NAVMESH_MESH = "DSMK_NavMeshZone"
NAVMESH_HALF = 100.0     # half side of the zone mesh (cm), like a ±100 cube brush
NAVMESH_SCALE = 10.0     # 20 m zone by default
PLAY_AREA_HALF = 1000.0  # half side of a new play area (cm): 20 m square


def half_height(p):
    """cm between the Blender origin (feet) and the game actor (capsule centre)."""
    if p.kind == "HOSTILE":
        return gd.ENEMY[p.enemy][2]
    if p.kind == "PEACEFUL":
        return gd.PEACEFUL_HALF_HEIGHT
    if p.kind == "PLAYERSTART":
        return gd.PLAYERSTART_HALF_HEIGHT
    return 0.0


def kit_objects(scene, kind=None):
    return [o for o in scene.objects if o.dsmk.kind != "NONE" and (kind is None or o.dsmk.kind == kind)]


def collection_for(scene, kind):
    name = f"{COLLECTION[kind]}_{scene.name}"
    for c in scene.collection.children_recursive:
        if c.name == name:
            return c
    coll = bpy.data.collections.new(name)
    scene.collection.children.link(coll)
    return coll


def next_name(scene, kind, taken=()):
    prefix = NAME_PREFIX[kind]
    used = {o.dsmk.ue_name for o in kit_objects(scene)} | set(taken)
    n = 0
    for name in used:
        m = re.fullmatch(re.escape(prefix) + r"_(\d+)", name)
        if m:
            n = max(n, int(m.group(1)) + 1)
    return f"{prefix}_{n}"


def _zone_mesh():
    me = bpy.data.meshes.get(NAVMESH_MESH)
    if me is None:
        d = NAVMESH_HALF
        verts = [(x, y, z) for x in (-d, d) for y in (-d, d) for z in (-d, d)]
        faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        me = bpy.data.meshes.new(NAVMESH_MESH)
        me.from_pydata(verts, [], faces)
        me.update()
    return me


def play_area_mesh(name, half=PLAY_AREA_HALF):
    """Square of side 2 * `half` (cm), faces looking down: the game looks for
    a play area face straight above the player (like the game's levels)."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([(-half, -half, 0.0), (half, -half, 0.0), (half, half, 0.0), (-half, half, 0.0)], [],
                   [(0, 3, 2, 1)])
    me.update()
    return me


def create(scene, kind, location=(0.0, 0.0, 0.0), name=None, data=None):
    """New kit object of `kind` at `location` (cm); `data`: mesh of a play area."""
    ue_name = name or next_name(scene, kind)
    if kind == "NAVMESH":
        data = _zone_mesh()
    elif kind == "PLAY_AREA" and data is None:
        data = play_area_mesh(ue_name)
    elif kind == "WINVIEW":
        data = bpy.data.cameras.new(ue_name)
        convert.setup_win_camera(data)
        data.display_size = 100.0
    obj = bpy.data.objects.new(ue_name, data)
    collection_for(scene, kind).objects.link(obj)
    obj.location = location
    p = obj.dsmk
    p.ue_name = ue_name
    if kind == "NAVMESH":
        obj.scale = (NAVMESH_SCALE,) * 3
    if kind in ("NAVMESH", "PLAY_AREA"):
        obj.display_type = "WIRE"
        obj.hide_render = True
        obj.visible_shadow = False
    if kind == "PATROL":
        p.rotate_character = p.stop  # new point: Stop? and RotateCharacter? both on
    p.kind = kind
    display.refresh(obj)
    return obj


def fix_duplicate_names(scene):
    """Copies (Shift+D) get a new actor name; returns the renamed objects."""
    seen, fixed = set(), []
    for o in sorted(kit_objects(scene), key=lambda o: (o.name != o.dsmk.ue_name, o.name)):
        p = o.dsmk
        if not p.ue_name or p.ue_name in seen or not gd.is_safe(p.ue_name):
            p.ue_name = next_name(scene, p.kind, seen)
            fixed.append(o)
        seen.add(p.ue_name)
    return fixed


# --- Export ---------------------------------------------------------------------------

def _matrix(o):
    return o.matrix_world if o.parent else o.matrix_basis


def _entry(o, cls):
    p = o.dsmk
    mw = _matrix(o)
    e = convert.pose_from_matrix(mw, None if o.parent else convert.signs_of(o.scale), half_height(p))
    e.update({"name": p.ue_name, "class": cls, "folder": gd.FOLDERS.get(cls, "Scene"), "blender_object": o.name})
    return e


def zone_box(o):
    """Axis-aligned box (game-frame cm) of a NavMesh zone, or None."""
    mw = _matrix(o)
    if o.type != "MESH" or not o.data.vertices:
        return None
    pts = [convert.M @ (mw @ v.co) for v in o.data.vertices]
    return ([round(min(q[i] for q in pts), 3) + 0.0 for i in range(3)],
            [round(max(q[i] for q in pts), 3) + 0.0 for i in range(3)])


def export_scene(scene):
    """Kit actors of the scene (dict for level_builder) and problems."""
    problems = []
    out = {k: [] for k in set(EXPORT_KEY.values())}
    out["win_views"], out["navmesh_zones"], out["play_areas"] = [], [], []
    objs = kit_objects(scene)
    if any(o.parent for o in objs):
        scene.view_layers[0].update()
    names = [o.dsmk.ue_name for o in objs]
    for n in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"actor name used twice: {n}")
    for o in sorted(objs, key=lambda o: o.dsmk.ue_name):
        p = o.dsmk
        if p.kind == "NAVMESH":
            rot, _s = convert.rotation_scale(_matrix(o).to_3x3())
            if (rot @ Vector((0.0, 0.0, 1.0))).z < 0.9999:
                problems.append(f"NavMesh zone {o.name}: only a rotation around Z is allowed (its bounding box is used)")
            box = zone_box(o)
            if box:
                out["navmesh_zones"].append({"blender_object": o.name, "min": box[0], "max": box[1]})
            continue
        if p.kind == "PLAY_AREA":
            # Its faces are exported as a mesh (export.py).
            if o.type != "MESH":
                problems.append(f"Play area {o.name}: not a mesh (ignored)")
            else:
                out["play_areas"].append({"blender_object": o.name, "name": p.ue_name})
            continue
        if p.kind == "WINVIEW":
            e = convert.winview_pose(_matrix(o))
            e.update({"name": p.ue_name, "class": gd.CLASS_WINVIEW, "blender_object": o.name})
            out["win_views"].append(e)
            continue
        cls = KIND_CLASS[p.kind]
        e = _entry(o, cls)
        props = {}
        if p.kind == "PATROL":
            if p.rotate_character != gd.DEFAULT_ROTATE:
                props["RotateCharacter?"] = str(p.rotate_character)
            if p.stop != gd.DEFAULT_STOP:
                props["Stop?"] = str(p.stop)
        elif p.kind == "TREE":
            if p.tree != gd.DEFAULT_TREE:
                props["SelectTree"] = gd.STATIC_MESH_REF.format(gd.TREE_PATH[p.tree])
        elif p.kind == "LADDER":
            props["Count"] = str(p.ladder_count)
            if p.two_sided:
                props["TwoSided?"] = "True"
        elif p.kind == "THROWABLE":
            path = next(t[2] for t in gd.THROWABLES if t[0] == p.throwable)
            props["Mesh"] = gd.STATIC_MESH_REF.format(path)
        elif p.kind == "PEACEFUL":
            if p.peaceful_type != gd.DEFAULT_PEACEFUL_TYPE:
                props["ChooseMesh"] = gd.PEACEFUL_MESH.format(t=p.peaceful_type)
            if p.start_static:
                props["StartStatic?"] = "True"
            if p.cant_panic:
                props["CantPanic?"] = "True"
        elif p.kind == "HOSTILE":
            targets = [it.target for it in p.patrol]
            if any(t is None for t in targets):
                problems.append(f"{p.ue_name}: empty patrol point (ignored)")
            targets = [t for t in targets if t is not None]
            for t in targets:
                if scene.objects.get(t.name) is None:
                    problems.append(f"{p.ue_name}: {t.dsmk.ue_name} is not in the scene {scene.name}")
            if p.state == gd.STATE_PATROLLING and not targets:
                problems.append(f"{p.ue_name}: Patrolling without patrol points")
            if p.enemy != gd.DEFAULT_ENEMY:
                props["E Enemies"] = p.enemy
            if p.weapon != gd.DEFAULT_WEAPON and not gd.is_melee(p.enemy):
                props["SelectWeapon"] = p.weapon
            if p.state != gd.DEFAULT_STATE:
                props["BehaviouralState"] = p.state
            for i, t in enumerate(targets):
                props[f"Patrolling Locations({i})"] = gd.PATROL_REF.format(t.dsmk.ue_name)
        if p.kind in ("PEACEFUL", "HOSTILE") and p.hair:
            props["ChooseHairHat"] = gd.HAIR_WOMAN
        e["props"] = props
        out[EXPORT_KEY[p.kind]].append(e)
    if len(out["win_views"]) > 1:
        problems.append(f"{len(out['win_views'])} win cameras: the game uses only one")
    if len(out["player_starts"]) > 1:
        problems.append(f"{len(out['player_starts'])} player starts: the game uses the first one")
    out["problems"] = problems
    return out, problems
