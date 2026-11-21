"""Building a new game level (JSON) in a mod folder from a Blender export.

Pure Python (no bpy): `build(...)` is called by the add-on after the Blender
export, and can be called from a test.

A new level is made of:
- the "base" actors of a game level chosen in the scene settings (level
  script with its music and fog, sky, post-process, navigation data, win box,
  win camera): `gamedata.BASE_CLASSES`;
- the scenery: one static mesh actor per exported Blender object (GLB in the
  world frame, complex collision that blocks everything);
- the kit actors (player start, NPCs, patrol points, ladders, air vents,
  trees, throwable objects, doors, end portal...): each one is a copy of a
  game actor of the same kind and look (same body, weapon, hair...), moved
  to its Blender place and given its Blender properties;
- the NavMesh zones of the scene (navigation is computed inside them);
- the play areas (out of bounds limit): invisible meshes that only the
  game's out of bounds test sees (one made above the whole level by the
  export when the scene has none).

Frames: the level JSON uses metres, Y up, quaternions [x, y, z, w]
(game frame X, Z, Y / 100); the export from Blender is already in this frame.
"""

import copy
import json
import os
import re

from . import gamedata as gd

API_VERSION = 1
MOD_TYPES = ("Level", "Asset Replacement", "Gameplay Mod")


# --- Transforms ---------------------------------------------------------------------

def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def qinv(q):
    n = sum(c * c for c in q) or 1.0
    return [-q[0] / n, -q[1] / n, -q[2] / n, q[3] / n]


def qrot(q, v):
    return qmul(qmul(q, [v[0], v[1], v[2], 0.0]), qinv(q))[:3]


def clean(v, nd=9):
    return [round(x, nd) + 0.0 for x in v]


class Delta:
    """From one actor pose to another (uniform scale assumed)."""

    def __init__(self, old, new):
        self.t0, self.r0, self.s0 = old["t"], old["r"], old.get("s", [1, 1, 1])
        self.t1, self.r1, self.s1 = new["t"], new["r"], new.get("s", [1, 1, 1])
        self.k = [b / a if a else 1.0 for a, b in zip(self.s0, self.s1)]
        self.q = qmul(self.r1, qinv(self.r0))

    def apply(self, e):
        if "t" not in e:
            return
        rel = [a - b for a, b in zip(e["t"], self.t0)]
        rel = qrot(qinv(self.r0), rel)
        rel = [v * k for v, k in zip(rel, self.k)]
        e["t"] = clean([a + b for a, b in zip(qrot(self.r1, rel), self.t1)])
        if "r" in e:
            e["r"] = clean(qmul(self.q, e["r"]))
        if "s" in e:
            e["s"] = clean([v * k for v, k in zip(e["s"], self.k)])
        for inst in e.get("instances") or []:
            self.apply(inst)


def move_actor(actor, meshes, pose):
    """Move the actor with its components and meshes (world poses)."""
    d = Delta(actor, pose)
    for c in actor.get("components", {}).values():
        d.apply(c)
    for m in meshes:
        d.apply(m)
    actor["t"], actor["r"], actor["s"] = clean(pose["t"]), clean(pose["r"]), clean(pose.get("s", [1, 1, 1]))


def rename(obj, old, new):
    """Replace the actor name `old` in every string (internal references)."""
    pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(old) + r"(?![A-Za-z0-9_])")
    if isinstance(obj, dict):
        return {k: rename(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rename(v, old, new) for v in obj]
    if isinstance(obj, str):
        return pat.sub(new, obj)
    return obj


def clone_actor(lv, name, new_name):
    a = next(a for a in lv["actors"] if a["name"] == name)
    a = rename(copy.deepcopy(a), name, new_name)
    ms = rename(copy.deepcopy(gd.actor_meshes(lv, name)), name, new_name)
    a["parent"] = None
    return a, ms


# --- Kit actors -------------------------------------------------------------------------

EXPORT_KEYS = ("patrolling_locations", "peaceful", "hostile", "player_starts", "trees", "ladders", "air_vents",
               "throwables")
# Properties set from Blender (removed from the copied actor first).
MANAGED = {
    gd.CLASS_PATROL: ("Stop?", "RotateCharacter?"),
    # Dialogue ("DialogueDataSheet" in the extracted game levels): the copied
    # character must not keep the dialogue of the original one.
    gd.CLASS_PEACEFUL: ("ChooseMesh", "DialogueDataSheet", "Name", "StartStatic?", "CantPanic?", "ChooseHairHat"),
    gd.CLASS_HOSTILE: ("E Enemies", "SelectWeapon", "BehaviouralState", "Patrolling Locations", "ChooseHairHat"),
    gd.CLASS_TREE: ("SelectTree", "RandomizeMaxAngle", "RandomizeMinScale", "RandomizeMaxScale", "DecalScale"),
    gd.CLASS_LADDER: ("Count", "TwoSided?"),
    gd.CLASS_THROWABLE: ("Mesh",),
}
# Properties kept from the copied actor (results of its construction script,
# settings of the throwable object that go with its mesh).
CONSTRUCTION = {
    gd.CLASS_HOSTILE: ("ST Enemies", "ST Weapon"),
    gd.CLASS_THROWABLE: ("PawnCollision?", "MassScaleWhenHolding", "MassScaleWhenNotHolding", "ObjectTargetOffset"),
}


def managed(cls, k):
    return any(k == m or k.startswith(m + "(") for m in MANAGED.get(cls, ()))


def compose_hostile(cache, key, new_name, first):
    """Enemy without an exact model in the game levels (e.g. a woman with
    hair and a weapon no woman has): body and hair of an enemy of the same
    type, weapon of another one (the weapon sits on the actor)."""
    enemy, weapon, hair = key
    if weapon == "-":
        return None
    body = arme = None
    for n in gd.template_levels(cache, first):
        lv = cache.level(n)
        for a in lv["actors"]:
            if a["class"] != gd.CLASS_HOSTILE:
                continue
            k = gd.compat_key(a["class"], a.get("props", {}))
            if body is None and k[0] == enemy and k[2] == hair and k[1] != "-":
                body = (lv, a["name"])
            if arme is None and k[1] == weapon:
                arme = (lv, a["name"])
        if body and arme:
            break
    if body is None or arme is None:
        return None
    base, ms = clone_actor(body[0], body[1], new_name)
    src = next(a for a in arme[0]["actors"] if a["name"] == arme[1])
    src_mesh = next((m for m in gd.actor_meshes(arme[0], arme[1]) if m["component"] == gd.WEAPON_COMPONENT), None)
    if src_mesh is None or gd.WEAPON_COMPONENT not in base.get("components", {}):
        return None
    base["components"][gd.WEAPON_COMPONENT]["props"] = copy.deepcopy(src["components"][gd.WEAPON_COMPONENT].get("props"))
    for m in ms:
        if m["component"] == gd.WEAPON_COMPONENT:
            m["mesh"], m["materials"] = src_mesh["mesh"], list(src_mesh["materials"])
    base.setdefault("props", {})["ST Weapon"] = src["props"]["ST Weapon"]
    return base, ms, f"{body[1]} ({body[0]['name']}) + weapon of {arme[1]} ({arme[0]['name']})"


def compose_ladder(cache, key, new_name, first):
    """Ladder without a model of the same Count: copy of a game ladder (same
    TwoSided? if possible), rungs and detection box rebuilt like its
    construction script (one rung every 35 cm)."""
    count, two = int(float(key[0])), str(key[1]).lower() == "true"
    src = None
    for n in gd.template_levels(cache, first):
        for a in cache.level(n)["actors"]:
            if a["class"] != gd.CLASS_LADDER:
                continue
            same = (str(a.get("props", {}).get("TwoSided?", "False")).lower() == "true") == two
            if src is None or (same and not src[2]):
                src = (n, a["name"], same)
        if src and src[2]:
            break
    if src is None:
        return None
    lv = cache.level(src[0])
    base, ms = clone_actor(lv, src[1], new_name)
    t, r = base["t"], base["r"]
    loc = lambda v: clean([a + b for a, b in zip(t, qrot(r, [v[0] / 100.0, v[2] / 100.0, v[1] / 100.0]))])
    comps = base.get("components", {})
    for m in ms:
        if m["component"] == gd.LADDER_HISM:
            s0 = (m.get("instances") or [{}])[0].get("s", [1.0, 1.0, 1.0])
            m["instances"] = [{"t": loc((0.0, 0.0, gd.LADDER_STEP * i)), "r": list(r), "s": list(s0)}
                              for i in range(count)]
    hism = comps.get(gd.LADDER_HISM)
    if hism is not None:
        props = {k: v for k, v in (hism.get("props") or {}).items()
                 if not k.startswith(("SortedInstances(", "PerInstanceSMData(", "InstanceReorderTable("))}
        props["NumBuiltInstances"] = props["InstanceCountToRender"] = str(count)
        for i in range(count):
            props[f"SortedInstances({i})"] = props[f"InstanceReorderTable({i})"] = str(i)
            if i:
                props[f"PerInstanceSMData({i})"] = (
                    "(Transform=(XPlane=(W=0.000000,X=1.000000,Y=0.000000,Z=0.000000),"
                    "YPlane=(W=0.000000,X=-0.000000,Y=1.000000,Z=0.000000),"
                    "ZPlane=(W=0.000000,X=0.000000,Y=-0.000000,Z=1.000000),"
                    f"WPlane=(W=1.000000,X=0.000000,Y=0.000000,Z={gd.LADDER_STEP * i:.6f})))")
        hism["props"] = props
    box = comps.get("BoxCollision")
    if box is not None:
        h = gd.LADDER_STEP * count / 2.0
        centre, ext = ((0.0, 0.0, h), (80.0, 45.0, h)) if two else ((20.0, 0.0, h), (40.0, 45.0, h))
        box["t"] = loc(centre)
        box.setdefault("props", {})["BoxExtent"] = "(X={:.6f},Y={:.6f},Z={:.6f})".format(*ext)
    return base, ms, f"{src[1]} ({lv['name']}) with {count} rungs"


def add_kit_actors(cache, L, acteurs, report, first):
    for e in [e for k in EXPORT_KEYS for e in acteurs.get(k, [])]:
        cls = e["class"]
        key = gd.compat_key(cls, e["props"])
        lv, tname = gd.find_template(cache, cls, key, first)
        composed = None
        if tname is None and cls == gd.CLASS_HOSTILE:
            composed = compose_hostile(cache, key, e["name"], first)
        if tname is None and cls == gd.CLASS_LADDER:
            composed = compose_ladder(cache, key, e["name"], first)
        if tname is None and composed is None:
            report["problems"].append(f"{e['name']}: no compatible game actor ({cls} {key})")
            continue
        if composed is not None:
            base, meshes, tname = composed
            report["copies"].append(f"{e['name']} <- {tname}")
        else:
            base, meshes = clone_actor(lv, tname, e["name"])
            report["copies"].append(f"{e['name']} <- {tname} ({lv['name']})")
        move_actor(base, meshes, e)
        props = {k: v for k, v in base.get("props", {}).items()
                 if not managed(cls, k) and k in CONSTRUCTION.get(cls, ())}
        props.update(e["props"])
        base["props"] = props
        base["folder"] = e.get("folder", base.get("folder"))
        L["actors"].append(base)
        L["meshes"].extend(meshes)


def add_prefabs(cache, L, acteurs, report, first):
    """Doors, end portal and other game actors placed as they are (copy of
    the first game actor of the class), and the win box (the one of the base
    level, moved)."""
    for e in acteurs.get("prefabs", []):
        cls = e["class"]
        existing = next((a for a in L["actors"] if a["class"] == cls), None) if cls == gd.CLASS_WON_BOX else None
        if existing is not None:
            move_actor(existing, gd.actor_meshes(L, existing["name"]), e)
            continue
        lv, tname = gd.find_template(cache, cls, None, first)
        if tname is None:
            report["problems"].append(f"{e['name']}: no {cls} in the game levels")
            continue
        base, meshes = clone_actor(lv, tname, e["name"])
        move_actor(base, meshes, e)
        base.setdefault("props", {}).update(e.get("props") or {})
        base["folder"] = e.get("folder", base.get("folder"))
        L["actors"].append(base)
        L["meshes"].extend(meshes)
        report["copies"].append(f"{e['name']} <- {tname} ({lv['name']})")


def place_win_view(L, acteurs, report):
    """Win camera of Blender: the base level's camera actor, moved with its
    components (kept where it is without a camera in Blender)."""
    vues = acteurs.get("win_views") or []
    actor = next((a for a in L["actors"] if a["class"] == gd.CLASS_WINVIEW), None)
    if not vues:
        if actor is not None:
            report["notes"].append("no win camera in the scene: the base level's one is kept where it is")
        return
    if actor is None:
        report["problems"].append("win camera: the base level has none")
        return
    move_actor(actor, gd.actor_meshes(L, actor["name"]), vues[0])


# --- Navigation ----------------------------------------------------------------------

def place_box(vol, mn, mx):
    """Cube brush volume (±100 cm) on the game-frame box min / max (cm)."""
    c = [(a + b) / 200.0 for a, b in zip(mn, mx)]
    h = [max(b - a, 1.0) / 200.0 for a, b in zip(mn, mx)]
    t, s = [c[0], c[2], c[1]], [h[0], h[2], h[1]]
    for e in [vol] + list(vol.get("components", {}).values()):
        e["t"], e["r"], e["s"] = clean(t), [0.0, 0.0, 0.0, 1.0], clean(s)


def brush_volume(name, cls, folder, props):
    comp = {"class": "BrushComponent", "t": [0.0, 0.0, 0.0], "r": [0.0, 0.0, 0.0, 1.0], "s": [1.0, 1.0, 1.0],
            "props": {"Brush": gd.MODEL_REF, "BrushBodySetup": gd.BODY_SETUP_REF},
            "collision": "NO_COLLISION", "collision_profile": "NoCollision", "mobility": "STATIC"}
    return {"name": name, "label": cls, "class": cls, "folder": folder, "tags": [], "hidden_in_game": False,
            "parent": None, "components": {"BrushComponent0": comp}, "t": [0.0, 0.0, 0.0],
            "r": [0.0, 0.0, 0.0, 1.0], "s": [1.0, 1.0, 1.0],
            "props": {**props, "BrushType": "Brush_Add", "Brush": gd.MODEL_REF, "BrushBuilder": gd.CUBE_BUILDER_REF}}


def add_nav_zones(L, zones, report):
    for i, z in enumerate(zones):
        vol = brush_volume(f"NavMeshBoundsVolume_{i}", gd.CLASS_NAV_BOUNDS, "Navigation",
                           {"SpawnCollisionHandlingMethod": "AlwaysSpawn"})
        place_box(vol, z["min"], z["max"])
        L["actors"].append(vol)
    report["nav_zones"] = len(zones)


# --- Scenery -------------------------------------------------------------------------

def collision_path(glb):
    """`collision/<path>.json` of a mesh `meshes/<path>.glb` (the game's rule)."""
    return "collision/" + os.path.splitext(glb[len("meshes/"):])[0] + ".json"


def static_mesh_ref(glb):
    p = "@game/" + os.path.splitext(glb[len("meshes/"):])[0]
    return gd.STATIC_MESH_REF.format(f"{p}.{p.rsplit('/', 1)[-1]}")


def write_json(path, data, compact=True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        if compact:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=1)


def add_scenery(L, geo, mod_dir, report):
    for e in geo.get("decor", []):
        g = geo["glb"].get(e["glb"])
        if g is None:
            report["problems"].append(f"{e['objet']}: not exported")
            continue
        pose = e["pose"]
        comp = {"class": gd.CLASS_STATIC_COMPONENT, "t": pose["t"], "r": pose["r"], "s": pose["s"],
                "props": {gd.STATIC_MESH_PROP: static_mesh_ref(e["glb"])},
                "collision": "QUERY_AND_PHYSICS", "collision_profile": "BlockAll", "mobility": "STATIC"}
        mesh = {"actor": e["acteur"], "component": gd.STATIC_COMPONENT_NAME, "mesh": e["glb"], "skeletal": False,
                "visible": True, "collision": "QUERY_AND_PHYSICS", "collision_profile": "BlockAll",
                "simulate_physics": False, "materials": g["materiaux"], "t": pose["t"], "r": pose["r"], "s": pose["s"]}
        actor = {"name": e["acteur"], "label": e["acteur"], "class": gd.CLASS_STATIC_ACTOR, "folder": "Scene",
                 "tags": [], "hidden_in_game": False, "parent": None,
                 "components": {gd.STATIC_COMPONENT_NAME: comp}, "t": pose["t"], "r": pose["r"], "s": pose["s"]}
        L["actors"].append(actor)
        L["meshes"].append(mesh)
        # Complex collision (triangles of the GLB), like the meshes of the game levels.
        write_json(os.path.join(mod_dir, *collision_path(e["glb"]).split("/")),
                   {"trace_flag": gd.TRACE_COMPLEX, "double_sided": False, "boxes": [], "spheres": [],
                    "capsules": [], "convexes": [], "profile": "BlockAll"})
        report["scenery"] += 1


def add_play_areas(L, geo, mod_dir, report):
    """Play areas: the player is out of bounds when no face of them is above
    (the game traces 400 m up on the OutOfBounds channel). Built like the out
    of bounds mesh of the game levels: hidden, blocks only that channel."""
    for e in geo.get("play_areas", []):
        g = geo["glb"].get(e["glb"])
        if g is None:
            continue
        t, r, s = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], [1.0, 1.0, 1.0]
        body = copy.deepcopy(gd.OUT_OF_BOUNDS_BODY)
        comp = {"class": gd.CLASS_STATIC_COMPONENT, "t": t, "r": r, "s": s,
                "props": {gd.STATIC_MESH_PROP: static_mesh_ref(e["glb"]), "bVisible": "False"},
                "collision": "QUERY_AND_PHYSICS", "collision_profile": "Custom", "body": body, "mobility": "STATIC"}
        mesh = {"actor": e["acteur"], "component": gd.STATIC_COMPONENT_NAME, "mesh": e["glb"], "skeletal": False,
                "visible": False, "collision": "QUERY_AND_PHYSICS", "collision_profile": "Custom",
                "simulate_physics": False, "materials": g["materiaux"], "t": t, "r": r, "s": s,
                "body": copy.deepcopy(body)}
        actor = {"name": e["acteur"], "label": e["acteur"], "class": gd.CLASS_STATIC_ACTOR,
                 "folder": gd.OUT_OF_BOUNDS_FOLDER, "tags": [], "hidden_in_game": False, "parent": None,
                 "components": {gd.STATIC_COMPONENT_NAME: comp}, "t": t, "r": r, "s": s}
        L["actors"].append(actor)
        L["meshes"].append(mesh)
        write_json(os.path.join(mod_dir, *collision_path(e["glb"]).split("/")),
                   {"trace_flag": gd.TRACE_COMPLEX, "double_sided": False, "boxes": [], "spheres": [],
                    "capsules": [], "convexes": []})
        if e.get("auto"):
            report["notes"].append("no play area in the scene: one above the whole level (out of bounds "
                                   "only outside it)")
    report["play_areas"] = len(geo.get("play_areas", []))


# --- Base level ------------------------------------------------------------------------

def base_actors(cache, base_level, L, report):
    lv = cache.level(base_level)
    for a in lv["actors"]:
        if a["class"] not in gd.BASE_CLASSES:
            continue
        a2 = copy.deepcopy(a)
        if a2["class"] == gd.CLASS_LEVEL_SCRIPT:
            for k in gd.BASE_SCRIPT_DROP:
                (a2.get("props") or {}).pop(k, None)
        L["actors"].append(a2)
        L["meshes"].extend(copy.deepcopy(gd.actor_meshes(lv, a["name"])))
    report["base_level"] = base_level


# --- Program ---------------------------------------------------------------------------

def level_file(map_name):
    """Level file of a mod (shipped layout: `levels/<map>.json`)."""
    return f"levels/{map_name}.json"


def drop_unshipped_materials(cache, L, report):
    """Material references copied with the game's actors that the installed
    game does not ship (the game never loads them): blockout material."""
    gone = cache.catalog().unshipped
    n = 0
    for m in L["meshes"]:
        mats = m.get("materials") or []
        for i, ref in enumerate(mats):
            if ref in gone:
                mats[i] = gd.FALLBACK_MATERIAL
                n += 1
    if n:
        report["notes"].append(f"{n} material reference(s) of game actors not shipped with the game: "
                               f"blockout material")


def build(cache, settings, geo, acteurs, mod_dir):
    """Write the level of `settings["map"]` in `mod_dir`. `geo`: exported
    scenery ({"glb": {path: {"materiaux": [...]}}, "decor": [...]}),
    `acteurs`: exported kit actors. Returns the report."""
    report = {"problems": list(geo.get("problemes", [])) + list(acteurs.get("problems", [])), "copies": [],
              "notes": [], "scenery": 0}
    map_name = settings["map"]
    if not gd.is_safe(map_name) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", map_name):
        raise ValueError(f"invalid level name: {map_name!r}")
    L = {"name": map_name, "package": f"@/Maps/{map_name}", "meshes": [], "actors": []}
    first = settings.get("base_level")
    base_actors(cache, first, L, report)
    zones = acteurs.get("navmesh_zones") or []
    if not zones and acteurs.get("auto_navmesh_zone"):
        zones = [acteurs["auto_navmesh_zone"]]
        report["notes"].append("no NavMesh zone in the scene: one zone around the whole level")
    add_nav_zones(L, zones, report)
    add_scenery(L, geo, mod_dir, report)
    add_play_areas(L, geo, mod_dir, report)
    add_kit_actors(cache, L, acteurs, report, first)
    add_prefabs(cache, L, acteurs, report, first)
    place_win_view(L, acteurs, report)
    drop_unshipped_materials(cache, L, report)
    if not any(a["class"] == gd.CLASS_PLAYERSTART for a in L["actors"]):
        report["problems"].append("no player start in the scene")
    if not any(a["class"] == gd.CLASS_END_PORTAL for a in L["actors"]):
        report["notes"].append("no end portal: the level cannot be won")
    names = [a["name"] for a in L["actors"]]
    for n in sorted({n for n in names if names.count(n) > 1}):
        report["problems"].append(f"actor name used twice: {n}")
    write_json(os.path.join(mod_dir, *level_file(map_name).split("/")), L)
    report["actors"] = len(L["actors"])
    return report


def read_mod_json(mod_dir):
    try:
        with open(os.path.join(mod_dir, "mod.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_mod_json(mod_dir, info):
    """mod.json at the root of the mod: fields of `info` set, other fields
    (e.g. the Workshop item id written by the game) kept."""
    data = read_mod_json(mod_dir)
    data.update({k: v for k, v in info.items() if v is not None})
    data.setdefault("api", API_VERSION)
    data.setdefault("requires", [])
    order = ["id", "name", "version", "api", "type", "levels", "requires"]
    data = {**{k: data[k] for k in order if k in data}, **{k: v for k, v in data.items() if k not in order}}
    write_json(os.path.join(mod_dir, "mod.json"), data, compact=False)
    return data
