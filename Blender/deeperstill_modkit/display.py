"""Display of the kit objects in Blender, with the game's own meshes.

The meshes come from the extracted game files (never from the kit): for a
kit object, the kit finds a game actor of the same kind and look (same
body, weapon, hair...) in the game levels and shows its meshes, placed as
in the game. Display models live in the scene `_DSMK_Models` (collections
`DSMK_Vis_*`, instanced by the kit objects); imported meshes are kept
(`DSMK_GLB_*`). Without extracted game files, kit objects show as empties.

Patrol routes of hostile NPCs are drawn as lines in the 3D view.
"""

import hashlib
import os

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from . import convert, kit
from . import gamedata as gd

MODELS_SCENE = "_DSMK_Models"
COLORS = {  # viewport colours of the display models (linear RGBA)
    "HOSTILE": (0.55, 0.06, 0.05, 1.0), "PEACEFUL": (0.08, 0.40, 0.10, 1.0), "PLAYERSTART": (0.05, 0.20, 0.65, 1.0),
    "PATROL": (0.90, 0.30, 0.02, 1.0), "PATROL_STOP": (0.80, 0.02, 0.02, 1.0), "LADDER": (0.35, 0.22, 0.10, 1.0),
    "AIRVENT": (0.45, 0.45, 0.48, 1.0), "TREE": (0.10, 0.30, 0.08, 1.0), "THROWABLE": (0.45, 0.30, 0.12, 1.0),
    "DOOR": (0.40, 0.25, 0.12, 1.0), "END_PORTAL": (0.55, 0.15, 0.75, 1.0), "WON_BOX": (0.30, 0.30, 0.30, 1.0),
}
EMPTY_LOOK = {"PLAYERSTART": ("SINGLE_ARROW", 100.0), "HOSTILE": ("SINGLE_ARROW", 80.0),
              "PEACEFUL": ("SINGLE_ARROW", 80.0), "PATROL": ("SPHERE", 25.0), "LADDER": ("ARROWS", 50.0),
              "AIRVENT": ("CUBE", 40.0), "TREE": ("CONE", 150.0), "THROWABLE": ("CUBE", 30.0),
              "DOOR": ("ARROWS", 100.0), "END_PORTAL": ("CIRCLE", 120.0), "WON_BOX": ("CUBE", 200.0)}


def _h(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def look_key(p):
    """What the display of a kit object depends on."""
    k = p.kind
    if k == "HOSTILE":
        return f"HOSTILE:{p.enemy}:{'-' if gd.is_melee(p.enemy) else p.weapon}:{int(p.hair)}"
    if k == "PEACEFUL":
        return f"PEACEFUL:{p.peaceful_type}:{int(p.hair)}"
    if k == "PATROL":
        return f"PATROL:{int(p.stop)}"
    if k == "LADDER":
        return f"LADDER:{p.ladder_count}:{int(p.two_sided)}"
    if k == "TREE":
        return f"TREE:{p.tree}"
    if k == "THROWABLE":
        return f"THROWABLE:{p.throwable}"
    return k


def template_props(p):
    """Properties of a game actor that looks like the kit object (for the search)."""
    props = {}
    if p.kind == "HOSTILE":
        props["E Enemies"] = p.enemy
        props["SelectWeapon"] = p.weapon
        if p.hair:
            props["ChooseHairHat"] = gd.HAIR_WOMAN
    elif p.kind == "PEACEFUL":
        if p.peaceful_type != gd.DEFAULT_PEACEFUL_TYPE:
            props["ChooseMesh"] = gd.PEACEFUL_MESH.format(t=p.peaceful_type)
        if p.hair:
            props["ChooseHairHat"] = gd.HAIR_WOMAN
    elif p.kind == "TREE" and p.tree != gd.DEFAULT_TREE:
        props["SelectTree"] = gd.STATIC_MESH_REF.format(gd.TREE_PATH[p.tree])
    elif p.kind == "THROWABLE":
        props["Mesh"] = gd.STATIC_MESH_REF.format(next(t[2] for t in gd.THROWABLES if t[0] == p.throwable))
    return props


def _models_scene():
    sc = bpy.data.scenes.get(MODELS_SCENE)
    if sc is None:
        sc = bpy.data.scenes.new(MODELS_SCENE)
        sc.unit_settings.scale_length = 0.01
    return sc


def _material(kind):
    name = f"DSMK_Display_{kind}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = COLORS.get(kind, (0.5, 0.5, 0.5, 1.0))
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = mat.diffuse_color
    return mat


BASIC_SHAPES = "@base/BasicShapes/"


def basic_shape(data_path):
    """Basic shapes (cube, sphere, cylinder, cone, plane: 100 cm, pivot at the
    centre) are made by the game itself, not shipped as files: made here too."""
    i = data_path.find(BASIC_SHAPES)
    if i < 0:
        return None
    import bmesh
    kind = data_path[i + len(BASIC_SHAPES):].split(".")[0]
    bm = bmesh.new()
    if kind == "Cube":
        bmesh.ops.create_cube(bm, size=100.0)
    elif kind == "Sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=50.0)
    elif kind == "Cylinder":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=50.0, radius2=50.0, depth=100.0)
    elif kind == "Cone":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=50.0, radius2=0.1, depth=100.0)
    elif kind == "Plane":
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=50.0)
    else:
        bm.free()
        return None
    me = bpy.data.meshes.new("DSMK_Shape")
    bm.to_mesh(me)
    bm.free()
    me["dsmk_glb"] = data_path
    return me


def import_glb(cache, data_path):
    """Mesh (cm, Blender frame) of a game GLB, imported once and kept; None if missing."""
    name = f"DSMK_GLB_{_h(data_path)}"
    me = bpy.data.meshes.get(name)
    if me is not None:
        return me
    shape = basic_shape(data_path)
    if shape is not None:
        shape.name = name
        return shape
    path = cache.file(data_path)
    if path is None:
        return None
    tmp = bpy.data.scenes.new("DSMK_Import")
    before = set(bpy.data.objects)
    mats_before, imgs_before = set(bpy.data.materials), set(bpy.data.images)
    try:
        with bpy.context.temp_override(scene=tmp, view_layer=tmp.view_layers[0]):
            bpy.ops.import_scene.gltf(filepath=path, import_shading="NORMALS", disable_bone_shape=True)
        new = [o for o in bpy.data.objects if o not in before]
        parts = []
        for o in new:
            if o.type == "MESH":
                m = o.data.copy()
                m.transform(Matrix.Scale(100.0, 4) @ o.matrix_world)
                parts.append(m)
        if not parts:
            return None
        me = parts[0]
        if len(parts) > 1:
            # Join the parts in one mesh (rare: GLB with several nodes).
            import bmesh
            bm = bmesh.new()
            for m in parts:
                bm.from_mesh(m)
            bm.to_mesh(me)
            bm.free()
            for m in parts[1:]:
                bpy.data.meshes.remove(m)
        me.name = name
        me["dsmk_glb"] = data_path
        me.materials.clear()
        for o in new:
            data = o.data
            bpy.data.objects.remove(o)
            if isinstance(data, bpy.types.Armature) and data.users == 0:
                bpy.data.armatures.remove(data)
            elif isinstance(data, bpy.types.Mesh) and data.users == 0 and data is not me:
                bpy.data.meshes.remove(data)
        for m in set(bpy.data.materials) - mats_before:
            if m.users == 0:
                bpy.data.materials.remove(m)
        for i in set(bpy.data.images) - imgs_before:
            if i.users == 0:
                bpy.data.images.remove(i)
        return me
    finally:
        for c in list(tmp.collection.children_recursive):
            bpy.data.collections.remove(c)
        bpy.data.scenes.remove(tmp)


def _template(cache, p):
    """(level, actor) of a game actor that looks like the kit object, or (None, None)."""
    from .props import KIND_CLASS
    cls = KIND_CLASS.get(p.kind)
    if cls is None:
        return None, None
    key = gd.compat_key(cls, template_props(p)) if cls in (gd.CLASS_HOSTILE, gd.CLASS_PEACEFUL, gd.CLASS_TREE,
                                                           gd.CLASS_THROWABLE) else None
    lv, name = gd.find_template(cache, cls, key)
    if name is None and cls == gd.CLASS_HOSTILE:  # body of the same type, any weapon
        for n in cache.level_names():
            lvl = cache.level(n)
            a = next((a for a in lvl["actors"] if a["class"] == cls
                      and gd.compat_key(cls, a.get("props", {}))[0] == p.enemy), None)
            if a is not None:
                return lvl, a["name"]
    if lv is None:
        return None, None
    return lv, next(a for a in lv["actors"] if a["name"] == name)


def _build(cache, p, key):
    """Display collection of a look (built from a game actor), or None."""
    from .actors import half_height
    lv, actor = _template(cache, p)
    if actor is None:
        return None
    coll = bpy.data.collections.new(f"DSMK_Vis_{_h(key)}")
    coll["dsmk_look"] = key
    _models_scene().collection.children.link(coll)
    origin = convert.blender_matrix_from_level(actor["t"], actor["r"], actor.get("s", [1, 1, 1]))
    origin = origin @ Matrix.Translation((0.0, 0.0, -half_height(p)))
    inv = origin.inverted()
    kind = "PATROL_STOP" if (p.kind == "PATROL" and p.stop) else p.kind
    mat = _material(kind)
    for m in gd.actor_meshes(lv, actor["name"]):
        if not m.get("visible", True) or "mesh" not in m:
            continue
        me = import_glb(cache, m["mesh"])
        if me is None:
            continue
        poses = m.get("instances") or [m]
        if p.kind == "LADDER" and m.get("instances"):
            first = convert.blender_matrix_from_level(poses[0]["t"], poses[0]["r"], poses[0].get("s", [1, 1, 1]))
            rel0 = inv @ first
            mats = [Matrix.Translation((0.0, 0.0, gd.LADDER_STEP * i)) @ rel0 for i in range(p.ladder_count)]
        else:
            mats = [inv @ convert.blender_matrix_from_level(q["t"], q["r"], q.get("s", [1, 1, 1])) for q in poses]
        for i, mx in enumerate(mats):
            ob = bpy.data.objects.new(f"{coll.name}_{m['component']}_{i}", me)
            ob.matrix_world = mx
            coll.objects.link(ob)
            if not me.materials:
                me.materials.append(None)
            for s in ob.material_slots:
                s.link = "OBJECT"
                s.material = mat
    return coll


def vis_collection(p, build=True):
    key = look_key(p)
    for c in bpy.data.collections:
        if c.get("dsmk_look") == key and c.name.startswith("DSMK_Vis_"):
            return c
    if not build or p.kind in ("NAVMESH", "WINVIEW", "PLAY_AREA", "NONE"):
        return None
    cache = kit.cache()
    if cache is None:
        return None
    try:
        return _build(cache, p, key)
    except (OSError, ValueError, KeyError, RuntimeError) as e:
        print(f"Deeper Still Mod Kit: display of {key}: {e}")
        return None


def refresh(obj, build=True):
    p = obj.dsmk
    if obj.type != "EMPTY":
        return
    look = EMPTY_LOOK.get(p.kind)
    if look:
        obj.empty_display_type, obj.empty_display_size = look
    coll = vis_collection(p, build) if p.kind != "NONE" else None
    if coll is not None:
        obj.instance_type = "COLLECTION"
        obj.instance_collection = coll
    else:
        obj.instance_type = "NONE"
        obj.instance_collection = None
    tag_redraw()


def refresh_all(rebuild=False):
    """Display of every kit object (rebuild: display models made again)."""
    if rebuild:
        for c in [c for c in bpy.data.collections if c.name.startswith("DSMK_Vis_")]:
            bpy.data.collections.remove(c)
    for o in bpy.data.objects:
        if o.dsmk.kind != "NONE":
            refresh(o)


# --- Patrol routes ----------------------------------------------------------------------

_handle = None


def tag_redraw():
    if bpy.app.background:
        return
    for w in getattr(bpy.context.window_manager, "windows", ()):
        for a in w.screen.areas:
            if a.type == "VIEW_3D":
                a.tag_redraw()


def _draw():
    scene = bpy.context.scene
    if scene is None:
        return
    lines, sel = [], []
    for o in scene.objects:
        p = o.dsmk
        if p.kind != "HOSTILE" or p.state != gd.STATE_PATROLLING:
            continue
        pts = [o.matrix_world.translation] + [it.target.matrix_world.translation for it in p.patrol
                                              if it.target is not None]
        if len(pts) < 2:
            continue
        seg = []
        for a, b in zip(pts[1:], pts[2:] + pts[1:2]):  # loop through the points
            seg += [a, b]
        seg += [pts[0], pts[1]]
        (sel if o.select_get() else lines).extend(seg)
    if not lines and not sel:
        return
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.line_width_set(2.0)
    gpu.state.depth_test_set("NONE")
    for pts, color in ((lines, (1.0, 0.45, 0.0, 0.6)), (sel, (1.0, 0.75, 0.1, 1.0))):
        if pts:
            batch = batch_for_shader(shader, "LINES", {"pos": [tuple(v) for v in pts]})
            shader.uniform_float("color", color)
            batch.draw(shader)
    gpu.state.line_width_set(1.0)


def register():
    global _handle
    if not bpy.app.background:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
