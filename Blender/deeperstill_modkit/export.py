"""Export of the level scene to a mod folder.

1. Scenery: every visible mesh or curve of the scene that is not a kit object
   is exported as a GLB (`meshes/<mod id>/<level>/<object>.glb`, evaluated
   mesh, world frame) with the same conventions as the game's meshes
   (centimetres, node scaled by 0.01, Y up, vertex colour = sRGB bytes of the
   `AO` attribute, one primitive per used material slot). Blender materials
   become game materials by name (`Concrete` -> the game's Concrete).
2. Kit actors (actors.export_scene). Play areas (out of bounds limit) are
   exported as GLB too (invisible in the game, only seen by the out of
   bounds test); without any, one is made above the whole level.
3. Level JSON, collisions and mod.json written by level_builder.
4. (ops.py) The game computes the level's navigation and writes it in the mod
   (`navmesh/<level>.nav`): NPCs move as soon as the level starts.

Non-destructive: a temporary scene is used and removed, the displayed scene,
selection, active object and mode are restored; nothing is saved.
Incremental: a GLB is written again only when its object changed (cache in
the kit's user folder, never in the mod folder).
"""

import re
import hashlib
import json
import math
import os
import shutil

import bpy
from mathutils import Matrix, Vector

from . import actors, convert, game, glb_fix, kit, level_builder, walls
from . import gamedata as gd

EXPORT_VERSION = 1


# --- Fingerprint -------------------------------------------------------------------

_COMPONENTS = {"FLOAT": ("value", 1, "f"), "INT": ("value", 1, "i"), "FLOAT_VECTOR": ("vector", 3, "f"),
               "FLOAT_COLOR": ("color", 4, "f"), "BYTE_COLOR": ("color", 4, "f"), "FLOAT2": ("vector", 2, "f"),
               "BOOLEAN": ("value", 1, "b"), "INT8": ("value", 1, "i"), "INT32_2D": ("value", 2, "i"),
               "QUATERNION": ("value", 4, "f")}


def _hash_coll(h, coll, attr, n, kind):
    import numpy as np
    a = np.empty(n, dtype={"f": np.float32, "i": np.int32, "b": bool}[kind])
    if n:
        coll.foreach_get(attr, a)
    h.update(a.tobytes())


def fingerprint(obj, depsgraph, matrix):
    """What the export of `obj` would write: evaluated mesh, materials, matrix."""
    h = hashlib.sha1()
    h.update(f"{EXPORT_VERSION}|".encode())
    h.update(repr([round(v, 6) for row in matrix for v in row]).encode())
    ev = obj.evaluated_get(depsgraph)
    h.update(repr([s.material.name if s.material else None for s in ev.material_slots]).encode())
    me = ev.to_mesh()
    try:
        if me is None:
            return h.hexdigest()
        h.update(f"{len(me.vertices)}|{len(me.loops)}|{len(me.polygons)}".encode())
        _hash_coll(h, me.vertices, "co", len(me.vertices) * 3, "f")
        _hash_coll(h, me.loops, "vertex_index", len(me.loops), "i")
        _hash_coll(h, me.polygons, "loop_start", len(me.polygons), "i")
        for a in sorted(me.attributes, key=lambda a: a.name):
            if a.name.startswith(".") or a.data_type not in _COMPONENTS:
                continue
            key, k, kind = _COMPONENTS[a.data_type]
            h.update(f"{a.name}|{a.domain}|{a.data_type}".encode())
            _hash_coll(h, a.data, key, len(a.data) * k, kind)
        _hash_coll(h, me.corner_normals, "vector", len(me.corner_normals) * 3, "f")
    finally:
        ev.to_mesh_clear()
    return h.hexdigest()


# --- Mesh and GLB -------------------------------------------------------------------

def mesh_for_export(obj, depsgraph, matrix):
    """Copy of the evaluated mesh of `obj`, transformed by `matrix`, with only
    the used material slots (order kept) and the AO colour as sRGB bytes.
    Returns (mesh, material names, triangles per slot)."""
    ev = obj.evaluated_get(depsgraph)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=depsgraph)
    me.transform(matrix)
    if matrix.determinant() < 0:
        me.flip_normals()
    me.calc_loop_triangles()
    used = sorted({t.material_index for t in me.loop_triangles})
    counts = {i: 0 for i in used}
    for t in me.loop_triangles:
        counts[t.material_index] += 1
    mats = [me.materials[i] if i < len(me.materials) else None for i in used]
    remap = {old: new for new, old in enumerate(used)}
    idx = [0] * len(me.polygons)
    me.polygons.foreach_get("material_index", idx)
    me.materials.clear()
    for m in mats:
        me.materials.append(m)
    me.polygons.foreach_set("material_index", [remap.get(i, 0) for i in idx])
    me.update()
    # The game reads COLOR_0 as the sRGB bytes of the attribute; the glTF
    # exporter writes a float colour as it is.
    for a in list(me.color_attributes):
        if a.name != "AO":
            me.color_attributes.remove(a)
    src = me.color_attributes.get("AO")
    if src is not None:
        vals = [c for e in src.data for c in e.color_srgb]
        col = me.color_attributes.new("Col", "FLOAT_COLOR", src.domain)
        col.data.foreach_set("color", vals)
        me.color_attributes.remove(me.color_attributes["AO"])
        me.color_attributes.active_color = me.color_attributes["Col"]
        me.color_attributes.render_color_index = me.color_attributes.active_color_index
    return me, [m.name if m else None for m in mats], [counts[i] for i in used]


def export_glb(me, name, path, scene):
    """Temporary object (scale 0.01: centimetres -> metres) exported alone."""
    ob = bpy.data.objects.new(name, me)
    me.name = name
    ob.scale = (0.01, 0.01, 0.01)
    scene.collection.objects.link(ob)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    vl = scene.view_layers[0]
    for o in vl.objects:
        if o is not None and o is not ob and o.select_get(view_layer=vl):
            o.select_set(False, view_layer=vl)
    ob.select_set(True, view_layer=vl)
    vl.objects.active = ob
    try:
        with bpy.context.temp_override(scene=scene, view_layer=vl):
            bpy.ops.export_scene.gltf(
                filepath=path, export_format="GLB", use_selection=True, use_active_scene=True, export_yup=True,
                export_apply=False, export_texcoords=True, export_normals=True, export_tangents=True,
                export_materials="PLACEHOLDER", export_vertex_color="ACTIVE",
                export_all_vertex_colors=False, export_cameras=False, export_lights=False,
                export_extras=False, export_skins=False, export_animations=False)
    finally:
        scene.collection.objects.unlink(ob)
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)


class _State:
    """Displayed scene, selection, active object and mode, restored after the export."""

    def __init__(self, context):
        self.windows = [(w, w.scene, w.view_layer) for w in context.window_manager.windows]
        self.mode = None
        obj = context.view_layer.objects.active if context.view_layer else None
        if obj is not None and obj.mode != "OBJECT":
            self.mode = obj.mode
            bpy.ops.object.mode_set(mode="OBJECT")
        self.active = obj
        self.selection = {}
        for sc in bpy.data.scenes:
            for vl in sc.view_layers:
                self.selection[(sc.name, vl.name)] = (
                    [o.name for o in vl.objects if o is not None and o.select_get(view_layer=vl)],
                    vl.objects.active.name if vl.objects.active else None)

    def restore(self):
        for w, sc, vl in self.windows:
            if w.scene != sc:
                w.scene = sc
            if vl is not None and w.view_layer != vl:
                w.view_layer = vl
        for (sc_name, vl_name), (names, active) in self.selection.items():
            sc = bpy.data.scenes.get(sc_name)
            vl = sc.view_layers.get(vl_name) if sc else None
            if vl is None:
                continue
            keep = set(names)
            for o in vl.objects:
                if o is not None and o.select_get(view_layer=vl) != (o.name in keep):
                    o.select_set(o.name in keep, view_layer=vl)
            vl.objects.active = vl.objects.get(active) if active else None
        if self.mode is not None and self.active is not None and bpy.context.view_layer.objects.active == self.active:
            try:
                bpy.ops.object.mode_set(mode=self.mode)
            except RuntimeError:
                pass


# --- Scenery -----------------------------------------------------------------------------

def scenery_objects(scene):
    """(exported objects, hidden objects ignored)."""
    vl = scene.view_layers[0]
    out, hidden = [], []
    for o in scene.objects:
        if o.type not in ("MESH", "CURVE") or o.dsmk.kind != "NONE":
            continue
        if o.dsmk_build.role in walls.NOT_EXPORTED:  # outlines and openings
            continue
        if o.instance_type == "COLLECTION":
            continue
        if not o.visible_get(view_layer=vl):
            hidden.append(o.name)
            continue
        out.append(o)
    return out, hidden


def valid_mod_id(v):
    """Same rule as the game (mod.json "id"): 1 to 64 lowercase letters, digits, '_', '-', '.',
    starting with a letter or a digit."""
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_.\-]{0,63}", v or ""))


def suggest_mod_id(v):
    s = re.sub(r"[^a-z0-9_.\-]+", "_", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", v or "").lower()).strip("_.-")
    return (s or "my_mod")[:64]


def check_settings(scene):
    """Mod id and level name of the scene, or ValueError with what to fix."""
    s = scene.dsmk
    if not valid_mod_id(s.mod_id):
        raise ValueError(f"Mod id {s.mod_id!r}: use lowercase letters, digits, '_', '-' or '.' only "
                         f"(suggestion: {suggest_mod_id(s.mod_id)})")
    v = s.map_name
    if not v or gd.safe_name(v) != v:
        raise ValueError(f"Level name {v!r}: use letters, digits and _ only (suggestion: {gd.safe_name(v)})")
    if not kit.mod_dir(scene):
        raise ValueError("choose a mod folder first")
    return s.mod_id, s.map_name


def _export_cache_path(mod_id, map_name):
    return os.path.join(game.user_data_dir(), "export_cache", f"{mod_id}_{map_name}.json")


def export_scene(context, mod_dir, cache, log=print):
    """Export the displayed scene into `mod_dir`. Returns (level report, lines)."""
    scene = context.scene
    s = scene.dsmk
    mod_id, map_name = check_settings(scene)
    if cache is None:
        raise RuntimeError("extract the game files first (Game > Extract game files)")
    if s.base_level not in cache.level_names():
        raise ValueError(f"base level {s.base_level!r} is not a game level")
    actors.fix_duplicate_names(scene)
    cpath = _export_cache_path(mod_id, map_name)
    try:
        with open(cpath, encoding="utf-8") as f:
            fcache = json.load(f)
    except (OSError, ValueError):
        fcache = {}
    state = _State(context)
    depsgraph = context.evaluated_depsgraph_get()
    depsgraph.update()
    catalog = cache.catalog()
    geo = {"glb": {}, "decor": [], "problemes": []}
    lines = []
    written, unchanged = [], 0
    tmp = None
    folder = f"meshes/{mod_id}/{map_name}"
    geo["play_areas"] = []
    auto_area = None
    try:
        objs, hidden = scenery_objects(scene)
        areas = actors.kit_objects(scene, "PLAY_AREA")
        if not areas:
            # No play area: one above the whole level (never out of bounds
            # above the level's footprint).
            auto_area = auto_play_area(scene, objs, depsgraph)
            if auto_area is not None:
                depsgraph.update()
        used = set()
        todo = [(o, False) for o in sorted(objs, key=lambda o: o.name)]
        todo += [(o, True) for o in sorted((o for o in areas if o.type == "MESH"), key=lambda o: o.dsmk.ue_name)]
        if auto_area is not None:
            todo.append((auto_area, True))
        for o, area in todo:
            base = gd.safe_name(o.dsmk.ue_name if area and o.dsmk.ue_name else o.name)
            n, k = base, 1
            while n.lower() in used:
                k += 1
                n = f"{base}_{k}"
            used.add(n.lower())
            rel = f"{folder}/{n}.glb"
            path = os.path.join(mod_dir, *rel.split("/"))
            mw = o.evaluated_get(depsgraph).matrix_world.copy()
            h = fingerprint(o, depsgraph, mw)
            hit = fcache.get(rel)
            if hit is not None and hit.get("fingerprint") == h and os.path.isfile(path):
                names, tris = hit["materials"], hit["triangles"]
                unchanged += 1
            else:
                me, names, tris = mesh_for_export(o, depsgraph, mw)
                if not tris:
                    bpy.data.meshes.remove(me)
                    geo["problemes"].append(f"{o.name}: no faces (ignored)")
                    continue
                if tmp is None:
                    tmp = bpy.data.scenes.new("DSMK_Export")
                export_glb(me, n, path, tmp)
                glb_fix.fix(path)
                written.append(rel)
                fcache[rel] = {"fingerprint": h, "materials": names, "triangles": tris}
            if area:
                # Never drawn: no material needed.
                geo["glb"][rel] = {"objet": o.name, "materiaux": [gd.FALLBACK_MATERIAL] * len(names),
                                   "triangles": tris}
                geo["play_areas"].append({"objet": o.name, "acteur": gd.make_safe(n), "glb": rel,
                                          "auto": o is auto_area})
                continue
            mats = []
            for name in names:
                full = catalog.find(name) if name else None
                if full is None:
                    geo["problemes"].append(f"{o.name}: Blender material {name!r} is not a game material "
                                            f"(grey blockout used)")
                    full = gd.FALLBACK_MATERIAL
                mats.append(full)
            geo["glb"][rel] = {"objet": o.name, "materiaux": mats, "triangles": tris}
            geo["decor"].append({"objet": o.name, "acteur": gd.make_safe(f"Scenery_{n}"), "glb": rel,
                                 "pose": {"t": [0.0, 0.0, 0.0], "r": [0.0, 0.0, 0.0, 1.0], "s": [1.0, 1.0, 1.0]}})
        # Files of objects that no longer exist.
        keep = {os.path.normcase(os.path.join(mod_dir, *r.split("/"))) for r in geo["glb"]}
        for sub, ext in ((folder, ".glb"), (f"collision/{mod_id}/{map_name}", ".json")):
            d = os.path.join(mod_dir, *sub.split("/"))
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                p = os.path.join(d, f)
                glb = os.path.normcase(os.path.join(mod_dir, *folder.split("/"), os.path.splitext(f)[0] + ".glb"))
                if f.endswith(ext) and glb not in keep:
                    os.remove(p)
        acteurs, _problems = actors.export_scene(scene)
        if not acteurs["navmesh_zones"]:
            acteurs["auto_navmesh_zone"] = auto_zone(scene, objs, depsgraph)
    finally:
        if auto_area is not None:
            me = auto_area.data
            bpy.data.objects.remove(auto_area)
            bpy.data.meshes.remove(me)
        if tmp is not None:
            bpy.data.scenes.remove(tmp)
        state.restore()
    os.makedirs(os.path.dirname(cpath), exist_ok=True)
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(fcache, f, indent=0)
    settings = {"mod_id": mod_id, "map": map_name, "base_level": s.base_level}
    report = level_builder.build(cache, settings, geo, acteurs, mod_dir)
    write_mod_json(scene, mod_dir)
    lines.append(f"Scenery: {len(written)} GLB written, {unchanged} unchanged")
    if hidden:
        lines.append(f"Hidden objects ignored: {', '.join(sorted(hidden))}")
    lines.append(f"Level {map_name}: {report['actors']} actors (base level {s.base_level})")
    for n in report["notes"]:
        lines.append(f"NOTE {n}")
    for p in report["problems"]:
        lines.append(f"PROBLEM {p}")
    log("\n".join(lines))
    return report, lines


def auto_play_area(scene, objs, depsgraph, margin=300.0, above=1000.0):
    """Temporary play area (object linked to the scene during the export only): a square above the scenery and the kit actors (win box and
    camera left out), `above` cm higher than the highest point, faces down.
    None without scenery."""
    pts = []
    for o in objs:
        mw = o.evaluated_get(depsgraph).matrix_world
        pts += [mw @ Vector(c) for c in o.bound_box]
    for o in actors.kit_objects(scene):
        if o.dsmk.kind not in ("NAVMESH", "WINVIEW", "WON_BOX", "PLAY_AREA"):
            pts.append(o.matrix_world.translation.copy())
    if not pts:
        return None
    x0, y0 = min(p.x for p in pts) - margin, min(p.y for p in pts) - margin
    x1, y1 = max(p.x for p in pts) + margin, max(p.y for p in pts) + margin
    z = max(p.z for p in pts) + above
    me = bpy.data.meshes.new("DSMK_PlayArea")
    me.from_pydata([(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)], [], [(0, 3, 2, 1)])
    me.update()
    ob = bpy.data.objects.new("DSMK_PlayArea", me)
    ob.dsmk.kind = "PLAY_AREA"
    ob.dsmk.ue_name = "PlayArea_Auto"
    scene.collection.objects.link(ob)  # evaluated with the scene; removed after the export
    return ob


def auto_zone(scene, objs, depsgraph, margin=300.0):
    """Box (game-frame cm) around the scenery and the kit actors."""
    pts = []
    for o in objs:
        mw = o.evaluated_get(depsgraph).matrix_world
        pts += [convert.M @ (mw @ Vector(c)) for c in o.bound_box]
    for o in actors.kit_objects(scene):
        if o.dsmk.kind not in ("NAVMESH", "WINVIEW", "PLAY_AREA"):
            pts.append(convert.M @ o.matrix_world.translation)
    if not pts:
        return None
    mn = [round(min(p[i] for p in pts) - margin, 3) for i in range(3)]
    mx = [round(max(p[i] for p in pts) + margin, 3) for i in range(3)]
    return {"blender_object": None, "min": mn, "max": mx}


def write_mod_json(scene, mod_dir):
    s = scene.dsmk
    data = level_builder.read_mod_json(mod_dir)
    levels = [l for l in data.get("levels", []) if isinstance(l, dict) and l.get("map") != s.map_name]
    entry = {"map": s.map_name, "title": s.level_title}
    if os.path.isfile(os.path.join(mod_dir, "preview.png")):
        entry["thumbnail"] = "preview.png"
    levels.append(entry)
    info = {"id": s.mod_id, "name": s.mod_name, "version": s.mod_version, "type": "Level", "levels": levels}
    if s.description:
        info["description"] = s.description
    return level_builder.write_mod_json(mod_dir, info)


# --- Player start for Play Here ------------------------------------------------------------

def _ignore_for_ground(obj):
    if obj is None:
        return True
    o = getattr(obj, "original", obj)
    if o.dsmk.kind != "NONE" or o.dsmk_build.role in walls.NOT_EXPORTED:
        return True
    return any(c.name.startswith("DSMK_Vis_") for c in o.users_collection)


def ground_under(scene, depsgraph, p, max_cm=100000.0):
    origin = Vector(p)
    for _ in range(64):
        hit, loc, _n, _i, obj, _m = scene.ray_cast(depsgraph, origin, Vector((0.0, 0.0, -1.0)), distance=max_cm)
        if not hit:
            return None
        if not _ignore_for_ground(obj):
            return loc
        origin = loc + Vector((0.0, 0.0, -0.5))
    return None


def view_point(context):
    rv3d = None
    space = context.space_data if context.area and context.area.type == "VIEW_3D" else None
    if space is not None:
        rv3d = space.region_3d
    if rv3d is None:
        for w in context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == "VIEW_3D":
                    rv3d = a.spaces.active.region_3d
                    break
            if rv3d is not None:
                break
    if rv3d is None:
        return None
    m = rv3d.view_matrix.inverted()
    fwd = m.to_3x3() @ Vector((0.0, 0.0, -1.0))
    return m.translation.copy(), math.atan2(fwd.y, fwd.x)


def start_pose(context, mode):
    """Level JSON pose of the player start for Play Here, or None (scene's player start)."""
    scene = context.scene
    if mode == "PLAYERSTART":
        return None
    if mode == "CURSOR":
        c = scene.cursor
        pos = c.location.copy() + Vector((0.0, 0.0, 50.0))
        x = c.matrix.to_3x3() @ Vector((1.0, 0.0, 0.0))
        yaw = math.atan2(x.y, x.x)
    else:
        v = view_point(context)
        if v is None:
            return None
        pos, yaw = v
    ground = ground_under(scene, context.evaluated_depsgraph_get(), pos)
    feet = (ground + Vector((0.0, 0.0, 2.0))) if ground is not None else pos - Vector((0.0, 0.0, gd.PLAYERSTART_HALF_HEIGHT))
    m = Matrix.Translation(feet) @ Matrix.Rotation(yaw, 4, "Z")
    return convert.pose_from_matrix(m, (1.0, 1.0, 1.0), gd.PLAYERSTART_HALF_HEIGHT)


def playtest_copy(mod_dir, map_name, mod_id, pose):
    """Copy of the mod for Play Here with the player start moved (the mod
    folder itself keeps the scene's player start). Returns its folder."""
    dst = os.path.join(game.user_data_dir(), "playtest", mod_id)
    for root, dirs, files in os.walk(mod_dir):
        rel = os.path.relpath(root, mod_dir)
        for f in files:
            a, b = os.path.join(root, f), os.path.join(dst, rel, f)
            try:
                sa, sb = os.stat(a), os.stat(b)
                if sa.st_size == sb.st_size and int(sa.st_mtime) == int(sb.st_mtime):
                    continue
            except OSError:
                pass
            os.makedirs(os.path.dirname(b), exist_ok=True)
            shutil.copy2(a, b)
    lpath = os.path.join(dst, *level_builder.level_file(map_name).split("/"))
    with open(lpath, encoding="utf-8") as f:
        L = json.load(f)
    starts = [a for a in L["actors"] if a["class"] == gd.CLASS_PLAYERSTART]
    for a in starts:
        level_builder.move_actor(a, gd.actor_meshes(L, a["name"]), pose)
    level_builder.write_json(lpath, L)
    return dst
