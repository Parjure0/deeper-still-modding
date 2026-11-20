"""Wall, floor and opening tools: real geometry made by the kit.

- **Wall**: an outline (edges, drawn from above) is extruded straight up
  (Height), given a Thickness on one side, cut by the openings of the scene
  and painted with the game's contact shadow (`AO` colour): optional dark
  band at the bottom (Dark base), white elsewhere.
- **Floor**: the faces of an outline become a slab (Thickness downwards),
  each face keeping its material.
- **Opening** (window, doorway): a box (Width, Height, Depth) or any closed
  mesh, never exported, cut out of the walls (and of the floors that ask for
  it); optional glass pane.

The outline is a child object of the wall or floor (wireframe, not
exported): *Edit Outline* selects it in Edit Mode; the wall is built again
when the outline, the settings or an opening change. The generated mesh is
an ordinary mesh (no modifier): what you see is what the game gets.
"""

import contextlib
import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import walls_geo as geo

ROLES = (
    ("NONE", "None", "", 0),
    ("WALL", "Wall", "Wall built from an outline of edges", 1),
    ("FLOOR", "Floor", "Floor slab built from an outline of faces", 2),
    ("OUTLINE", "Outline", "Outline of a wall or floor (not exported)", 3),
    ("OPENING", "Opening", "Opening cut out of the walls (not exported)", 4),
)
NOT_EXPORTED = {"OUTLINE", "OPENING"}
OUTLINE_SUFFIX = "_Outline"
GLASS_SUFFIX = "_Glass"
GLASS_MATERIAL = "Glass"
OPENING_COLOR = (0.15, 0.55, 0.95, 1.0)
OUTLINE_COLOR = (1.0, 0.55, 0.0, 1.0)
TARGET_NORMAL_Z = -0.9   # wall faces looking down: bottom of the wall (dark band)
RAY_EXTRA = 10.0         # ray length = band height + 10 cm
USE_SELF = False         # like a Boolean modifier: openings should not overlap each other

_state = {"suspend": 0, "building": 0, "pending": set(), "openings": set(), "sigs": {}}


def _sig(obj):
    """Placement and shape of an object (to ignore updates that change nothing)."""
    m = tuple(round(v, 4) for row in obj.matrix_world for v in row)
    me = obj.data if obj.type == "MESH" else None
    if me is None:
        return m
    return m, len(me.vertices), tuple(round(v, 3) for c in obj.bound_box for v in c)


def _changed_since_build(obj):
    s = _sig(obj)
    if _state["sigs"].get(obj.name) == s:
        return False
    _state["sigs"][obj.name] = s
    return True


# --- Settings ---------------------------------------------------------------------------

def _changed(self, context):
    obj = self.id_data
    if not isinstance(obj, bpy.types.Object):
        return
    if self.role in ("WALL", "FLOOR"):
        schedule(obj)
    elif self.role == "OPENING":
        schedule_opening(obj)


class DSMK_BuildProps(bpy.types.PropertyGroup):
    role: EnumProperty(name="Role", items=ROLES, default="NONE")
    outline: PointerProperty(name="Outline", type=bpy.types.Object,
                             description="Outline object of the wall or floor (child object)")
    # Wall
    height: FloatProperty(name="Height", subtype="DISTANCE", default=400.0, min=0.0, soft_max=5000.0,
                          update=_changed, description="Height of the wall above its outline")
    thickness: FloatProperty(name="Thickness", subtype="DISTANCE", default=30.0, min=0.0, soft_max=200.0,
                             update=_changed, description="Thickness of the wall")
    offset: FloatProperty(name="Offset", default=-1.0, min=-1.0, max=1.0, update=_changed,
                          description="Side of the thickness: -1 on the right of the outline edges (walking along "
                                      "an edge, seen from above), 1 on the left, 0 centred")
    dark_base: BoolProperty(name="Dark Base", default=False, update=_changed,
                            description="Contact shadow of the game: dark at the bottom of the wall, fading to "
                                        "white at the Dark Height")
    dark_height: FloatProperty(name="Dark Height", subtype="DISTANCE", default=30.0, min=0.0, soft_max=2000.0,
                               update=_changed, description="Height of the dark band (the wall height when higher)")
    # Floor
    floor_thickness: FloatProperty(name="Thickness", subtype="DISTANCE", default=40.0, min=0.0, soft_max=500.0,
                                   update=_changed, description="Thickness of the slab, below its outline faces")
    # Wall and floor
    use_openings: BoolProperty(name="Cut Openings", default=True, update=_changed,
                               description="Cut the openings of the scene out of this object")
    uv_tile: FloatProperty(name="UV Tile", subtype="DISTANCE", default=400.0, min=0.0, soft_max=2000.0,
                           update=_changed, description="Box UV projection, one texture tile every this "
                                                         "distance (0: no UV map)")
    smooth_angle: FloatProperty(name="Smooth Angle", subtype="ANGLE", default=math.radians(30.0), min=0.0,
                                max=math.pi, update=_changed,
                                description="Edges sharper than this angle are shaded sharp")
    # Opening
    width: FloatProperty(name="Width", subtype="DISTANCE", default=120.0, min=1.0, soft_max=2000.0,
                         update=_changed)
    opening_height: FloatProperty(name="Height", subtype="DISTANCE", default=130.0, min=1.0, soft_max=2000.0,
                                  update=_changed)
    depth: FloatProperty(name="Depth", subtype="DISTANCE", default=100.0, min=1.0, soft_max=1000.0,
                         update=_changed, description="Depth of the cut (more than the wall thickness), "
                                                      "centred on the opening's origin")
    custom_shape: BoolProperty(name="Custom Shape", default=False, update=_changed,
                               description="The opening is the object's own closed mesh (Width, Height and "
                                           "Depth are not used)")
    glass: BoolProperty(name="Glass Pane", default=False, update=_changed,
                        description="Pane of glass in the opening (exported as scenery)")
    glass_offset: FloatProperty(name="Glass Offset", subtype="DISTANCE", default=0.0, update=_changed,
                                description="Position of the pane along the opening's Y axis")
    glass_material: PointerProperty(name="Glass Material", type=bpy.types.Material, update=_changed,
                                    description="Material of the pane (empty: the game material Glass)")
    glass_object: PointerProperty(name="Glass Object", type=bpy.types.Object)


def props(obj):
    return obj.dsmk_build


def role(obj):
    return obj.dsmk_build.role if obj is not None else "NONE"


# --- Rebuild scheduling -------------------------------------------------------------------

@contextlib.contextmanager
def suspended():
    """No automatic rebuild inside the block (scripts that change many settings)."""
    _state["suspend"] += 1
    try:
        yield
    finally:
        _state["suspend"] -= 1


def _run_pending():
    names, ops = set(_state["pending"]), set(_state["openings"])
    _state["pending"].clear()
    _state["openings"].clear()
    for n in ops:
        o = bpy.data.objects.get(n)
        if o is not None and role(o) == "OPENING":
            build_opening(o)
            names |= {w.name for w in walls_cut_by(o)}
    for n in names:
        o = bpy.data.objects.get(n)
        if o is not None and role(o) in ("WALL", "FLOOR"):
            try:
                build(o)
            except Exception as e:  # noqa: BLE001 - a broken outline must not stop the others
                print(f"Deeper Still: {o.name} not built: {e}")
    return None


def _kick():
    if _state["suspend"]:
        return
    if bpy.app.background:
        _run_pending()
    elif not bpy.app.timers.is_registered(_run_pending):
        bpy.app.timers.register(_run_pending, first_interval=0.15)


def schedule(obj):
    if _state["suspend"]:
        return
    _state["pending"].add(obj.name)
    _kick()


def schedule_opening(obj):
    if _state["suspend"]:
        return
    _state["openings"].add(obj.name)
    _kick()


def walls_cut_by(opening):
    """Walls and floors of the opening's scenes that cut openings."""
    out = []
    for sc in opening.users_scene:
        out += [o for o in sc.objects if role(o) in ("WALL", "FLOOR") and o.dsmk_build.use_openings]
    return out


def on_depsgraph(scene, depsgraph):
    """Outline edited or opening moved: rebuild what depends on it (interactive
    sessions only: scripts build explicitly)."""
    if _state["suspend"] or _state["building"] or bpy.app.background:
        return
    for u in depsgraph.updates:
        ob = u.id
        if not isinstance(ob, bpy.types.Object):
            continue
        ob = ob.original
        r = role(ob)
        if r == "OUTLINE" and u.is_updated_geometry:
            if ob.parent is not None and role(ob.parent) in ("WALL", "FLOOR"):
                schedule(ob.parent)
        elif r == "OPENING" and (u.is_updated_geometry or u.is_updated_transform) and _changed_since_build(ob):
            for w in walls_cut_by(ob):
                schedule(w)
        elif (r in ("WALL", "FLOOR") and u.is_updated_transform and ob.dsmk_build.use_openings
              and _changed_since_build(ob)):
            schedule(ob)


def fix_copies(scene):
    """Copies (Shift+D) of a wall get their own outline, copies of an opening their own pane."""
    for o in list(scene.objects):
        r = role(o)
        p = o.dsmk_build
        if r in ("WALL", "FLOOR") and p.outline is not None and p.outline.parent != o:
            src = p.outline
            new = src.copy()
            new.data = src.data.copy()
            for c in o.users_collection:
                c.objects.link(new)
            new.parent = o
            new.matrix_parent_inverse = Matrix.Identity(4)
            new.matrix_basis = src.matrix_basis.copy()
            new.name = o.name + OUTLINE_SUFFIX
            p.outline = new
        elif r == "OPENING" and p.glass_object is not None and p.glass_object.parent != o:
            p.glass_object = None
            build_opening(o)


# --- Outline ------------------------------------------------------------------------------

def _outline_geometry(outline):
    """(points, edges, faces, face materials) of the outline, in its parent's frame."""
    m = outline.matrix_basis if outline.parent is not None else Matrix.Identity(4)
    if outline.mode == "EDIT":
        import bmesh
        bm = bmesh.from_edit_mesh(outline.data)
        bm.verts.ensure_lookup_table()
        pts = [tuple(m @ v.co) for v in bm.verts]
        edges = [(e.verts[0].index, e.verts[1].index) for e in bm.edges]
        faces = [[v.index for v in f.verts] for f in bm.faces]
        mats = [f.material_index for f in bm.faces]
        return pts, edges, faces, mats
    me = outline.data
    pts = [tuple(m @ v.co) for v in me.vertices]
    edges = [tuple(e.vertices) for e in me.edges]
    faces = [list(p.vertices) for p in me.polygons]
    mats = [p.material_index for p in me.polygons]
    return pts, edges, faces, mats


def make_build(obj, kind, outline_mesh=None):
    """`obj` (mesh object) becomes a wall or floor. Its outline is
    `outline_mesh`, or the object's current mesh. Returns the outline object."""
    p = obj.dsmk_build
    src = outline_mesh if outline_mesh is not None else obj.data
    if outline_mesh is None:
        obj.data = bpy.data.meshes.new(obj.name)
        for m in src.materials:
            obj.data.materials.append(m)
    ol = bpy.data.objects.new(obj.name + OUTLINE_SUFFIX, src)
    for c in obj.users_collection:
        c.objects.link(ol)
    ol.parent = obj
    ol.matrix_parent_inverse = Matrix.Identity(4)
    ol.display_type = "WIRE"
    ol.show_in_front = True
    ol.hide_render = True
    ol.visible_shadow = False
    ol.color = OUTLINE_COLOR
    ol.dsmk_build.role = "OUTLINE"
    with suspended():
        p.role = kind
        p.outline = ol
        if kind == "FLOOR":
            p.use_openings = False
    return ol


def make_opening(obj, custom=True):
    """`obj` becomes an opening (its own mesh when `custom`, else a box)."""
    with suspended():
        p = obj.dsmk_build
        p.role = "OPENING"
        p.custom_shape = custom
    obj.display_type = "WIRE"
    obj.show_in_front = True
    obj.hide_render = True
    obj.visible_shadow = False
    obj.color = OPENING_COLOR
    build_opening(obj)
    return obj


# --- Build ---------------------------------------------------------------------------------

def _scene_of(obj):
    sc = bpy.context.scene
    if sc is not None and sc.objects.get(obj.name) is obj:
        return sc
    return obj.users_scene[0] if obj.users_scene else sc


def _cutter(obj, scene, bounds):
    """Openings of the scene that touch `bounds` (local box of the object),
    joined in one mesh in the object's frame, or None."""
    inv = obj.matrix_world.inverted()
    (lx, ly, lz), (hx, hy, hz) = bounds
    verts, faces = [], []
    depsgraph = None
    for op in scene.objects:
        if role(op) != "OPENING" or op.type != "MESH":
            continue
        m = inv @ op.matrix_world
        pts = [m @ Vector(c) for c in op.bound_box]
        if (max(q.x for q in pts) < lx or min(q.x for q in pts) > hx or max(q.y for q in pts) < ly
                or min(q.y for q in pts) > hy or max(q.z for q in pts) < lz or min(q.z for q in pts) > hz):
            continue
        me = op.data
        base = len(verts)
        verts += [tuple(m @ v.co) for v in me.vertices]
        faces += [[base + i for i in p.vertices] for p in me.polygons]
    if not faces:
        return None
    me = bpy.data.meshes.new("DSMK_Cutter")
    me.from_pydata(verts, [], faces)
    me.update()
    return me


def _local_bounds(points, zmin, zmax, margin):
    if not points:
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return ((min(xs) - margin, min(ys) - margin, min(zs) + zmin - margin),
            (max(xs) + margin, max(ys) + margin, max(zs) + zmax + margin))


def _evaluate(scene, me, materials, wall=None, cutter=None):
    """`me` with the wall thickness and the openings cut, as a new mesh."""
    for m in materials:
        me.materials.append(m)
    tmp = bpy.data.objects.new("DSMK_Build", me)
    scene.collection.objects.link(tmp)
    cut = None
    try:
        if wall is not None:
            s = tmp.modifiers.new("Thickness", "SOLIDIFY")
            s.thickness = wall.thickness
            s.offset = wall.offset
            s.use_even_offset = True
            s.use_rim = True
            s.solidify_mode = "NON_MANIFOLD"
            s.nonmanifold_thickness_mode = "CONSTRAINTS"
            s.use_quality_normals = False
        if cutter is not None:
            cut = bpy.data.objects.new("DSMK_Cutter", cutter)
            scene.collection.objects.link(cut)
            b = tmp.modifiers.new("Openings", "BOOLEAN")
            b.operation = "DIFFERENCE"
            b.operand_type = "OBJECT"
            b.object = cut
            b.solver = "EXACT"
            b.use_self = USE_SELF
        vl = scene.view_layers[0]
        dg = vl.depsgraph
        dg.update()
        ev = tmp.evaluated_get(dg)
        return bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    finally:
        bpy.data.objects.remove(tmp)
        bpy.data.meshes.remove(me)
        if cut is not None:
            bpy.data.objects.remove(cut)
        if cutter is not None and cutter.users == 0:
            bpy.data.meshes.remove(cutter)


def _paint_ao(me, dark_base, ao_height):
    """`AO` corner colour: dark band at the bottom of the walls (Dark Base),
    white elsewhere (alpha 0)."""
    n_loops = len(me.loops)
    colors = [1.0, 1.0, 1.0, 0.0] * n_loops
    wall_attr = me.attributes.get("AO_Wall")
    if dark_base and wall_attr is not None and len(me.polygons):
        verts = [v.co.copy() for v in me.vertices]
        wall = [d.value for d in wall_attr.data]
        targets = [list(p.vertices) for p, w in zip(me.polygons, wall)
                   if p.normal.z < TARGET_NORMAL_Z and w > 0.5]
        if targets:
            tree = BVHTree.FromPolygons(verts, targets, all_triangles=False)
            length = ao_height + RAY_EXTRA
            down = Vector((0.0, 0.0, -1.0))
            up = Vector((0.0, 0.0, 0.5))
            for p in me.polygons:
                n = p.normal
                t = Vector((-n.y, n.x, 0.0))
                t = t.normalized() if t.length > 0.0 else t
                inner = -0.5 * n + up
                for li in p.loop_indices:
                    co = verts[me.loops[li].vertex_index] + inner
                    best, hit = 1000000.0, False
                    for s in (co + 0.5 * t, co - 0.5 * t):
                        loc, _n, _i, dist = tree.ray_cast(s, down, length)
                        if loc is not None:
                            hit = True
                            best = min(best, dist)
                    f = geo.dark_base_factor(best, ao_height, hit)
                    c = 1.0 - f
                    colors[li * 4:li * 4 + 3] = [c, c, c]
    for name in ("AO_Wall", "AO_Base", "AO_Height"):
        a = me.attributes.get(name)
        if a is not None:
            me.attributes.remove(a)
    ao = me.color_attributes.get("AO")
    if ao is not None:
        me.color_attributes.remove(ao)
    ao = me.color_attributes.new("AO", "BYTE_COLOR", "CORNER")
    ao.data.foreach_set("color", colors)
    me.color_attributes.active_color = ao


def _smooth(me, angle):
    """Faces shaded smooth, edges sharper than `angle` (2 faces) sharp."""
    if not len(me.polygons):
        return
    faces_of = {}
    for p in me.polygons:
        for k in p.loop_indices:
            faces_of.setdefault(me.loops[k].edge_index, []).append(p.index)
    sharp = [False] * len(me.edges)
    normals = [p.normal.copy() for p in me.polygons]
    for e, fs in faces_of.items():
        if len(fs) == 2 and geo.face_angle(normals[fs[0]], normals[fs[1]]) > angle + 1e-6:
            sharp[e] = True
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    a = me.attributes.get("sharp_edge") or me.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
    a.data.foreach_set("value", sharp)


def _uv(me, matrix, tile):
    if tile <= 0.0 or not len(me.polygons):
        return
    uv = me.uv_layers.new(name="UVMap")
    rot = matrix.to_3x3()
    for p in me.polygons:
        n = rot @ p.normal
        for li in p.loop_indices:
            co = matrix @ me.vertices[me.loops[li].vertex_index].co
            uv.data[li].uv = geo.box_uv(co, n, tile)


def generated_mesh(obj, scene=None):
    """New mesh of the wall or floor `obj` from its outline and settings."""
    p = obj.dsmk_build
    ol = p.outline
    if ol is None or ol.type != "MESH":
        raise ValueError("no outline")
    scene = scene or _scene_of(obj)
    pts, edges, faces, mats = _outline_geometry(ol)
    materials = list(ol.data.materials)
    me = bpy.data.meshes.new("DSMK_Build")
    if p.role == "WALL":
        g = geo.extrude_edges(pts, edges, p.height, p.dark_base, p.dark_height)
        me.from_pydata(g["verts"], [], g["faces"])
        a = me.attributes.new("AO_Base", "FLOAT", "POINT")
        a.data.foreach_set("value", g["ao_base"])
        me.attributes.new("AO_Height", "FLOAT", "POINT").data.foreach_set("value", [g["ao_height"]] * len(g["verts"]))
        me.attributes.new("AO_Wall", "FLOAT", "FACE").data.foreach_set("value", [1.0] * len(g["faces"]))
        bounds = _local_bounds(pts, 0.0, p.height, p.thickness + 1.0)
        ao_height, dark = g["ao_height"], p.dark_base
    else:
        g = geo.extrude_floor(pts, faces, p.floor_thickness)
        me.from_pydata(g["verts"], [], g["faces"])
        me.polygons.foreach_set("material_index", [mats[s] for s in g["source"]])
        bounds = _local_bounds(pts, -p.floor_thickness, 0.0, 1.0)
        ao_height, dark = 0.0, False
    me.update()
    cutter = _cutter(obj, scene, bounds) if p.use_openings else None
    out = _evaluate(scene, me, materials, wall=p if p.role == "WALL" else None, cutter=cutter)
    _paint_ao(out, dark, ao_height)
    _smooth(out, p.smooth_angle)
    _uv(out, obj.matrix_world, p.uv_tile)
    return out


def build(obj, scene=None):
    """Build the wall or floor `obj` again (its mesh is replaced)."""
    _state["building"] += 1
    try:
        return _build(obj, scene)
    finally:
        _state["building"] -= 1


def _build(obj, scene):
    out = generated_mesh(obj, scene)
    old = obj.data
    name = old.name if old is not None else obj.name
    if old is not None:
        old.name = name + "_old"
    out.name = name
    obj.data = out
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)
    _state["sigs"][obj.name] = _sig(obj)
    return obj


def build_opening(obj):
    """Box of a box opening, glass pane (child object) when asked."""
    p = obj.dsmk_build
    if not p.custom_shape and obj.type == "MESH":
        verts, faces = geo.box_mesh(p.width, p.depth, p.opening_height)
        me = obj.data
        me.clear_geometry()
        me.from_pydata(verts, [], faces)
        me.update()
    _state["sigs"][obj.name] = _sig(obj)
    pane = p.glass_object
    if not p.glass:
        if pane is not None:
            mesh = pane.data
            bpy.data.objects.remove(pane)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            p.glass_object = None
        return
    if obj.type != "MESH" or not len(obj.data.vertices):
        return
    xs = [v.co.x for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    x0, x1, z0, z1, y = min(xs), max(xs), min(zs), max(zs), p.glass_offset
    verts = [(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)] * 2
    faces = [(0, 1, 2, 3), (7, 6, 5, 4)]  # one face for each side
    if pane is None:
        me = bpy.data.meshes.new(obj.name + GLASS_SUFFIX)
        pane = bpy.data.objects.new(obj.name + GLASS_SUFFIX, me)
        for c in obj.users_collection:
            c.objects.link(pane)
        pane.parent = obj
        pane.matrix_parent_inverse = Matrix.Identity(4)
        pane.hide_select = False
        p.glass_object = pane
    me = pane.data
    me.clear_geometry()
    me.from_pydata(verts, [], faces)
    me.update()
    mat = p.glass_material
    if mat is None:
        from . import materials
        mat = materials.ensure_material(GLASS_MATERIAL)
    me.materials.clear()
    me.materials.append(mat)


def freeze(obj):
    """Wall or floor -> ordinary mesh (its outline is deleted)."""
    p = obj.dsmk_build
    ol = p.outline
    with suspended():
        p.outline = None
        p.role = "NONE"
    if ol is not None:
        mesh = ol.data
        bpy.data.objects.remove(ol)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


# --- Operators -----------------------------------------------------------------------------

def _new_object(context, name, verts, edges, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    context.collection.objects.link(ob)
    ob.location = context.scene.cursor.location
    return ob


def _select_only(context, obj):
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


class DSMK_OT_build_add(bpy.types.Operator):
    """Make walls (or floors) from the selected meshes, or add a new one at the 3D cursor"""
    bl_idname = "dsmk.build_add"
    bl_label = "Add Wall"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(items=(("WALL", "Wall", "Wall from the edges of an outline"),
                              ("FLOOR", "Floor", "Floor slab from the faces of an outline")))

    @classmethod
    def description(cls, context, props):
        if props.kind == "FLOOR":
            return ("Make floors from the selected meshes (their faces), or add a new 6 m x 4 m floor at the "
                    "3D cursor")
        return "Make walls from the selected meshes (their edges), or add a new 6 m x 4 m room at the 3D cursor"

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        objs = [o for o in context.selected_objects if o.type == "MESH" and role(o) == "NONE"
                and getattr(o, "dsmk", None) is not None and o.dsmk.kind == "NONE"]
        if not objs:
            pts = [(-300.0, -200.0, 0.0), (300.0, -200.0, 0.0), (300.0, 200.0, 0.0), (-300.0, 200.0, 0.0)]
            if self.kind == "WALL":
                ob = _new_object(context, "Wall", pts, [(0, 1), (1, 2), (2, 3), (3, 0)], [])
            else:
                ob = _new_object(context, "Floor", pts, [], [(0, 1, 2, 3)])
            objs = [ob]
        for o in objs:
            if self.kind == "FLOOR" and not len(o.data.polygons):
                self.report({"WARNING"}, f"{o.name}: no faces, not a floor outline")
                continue
            make_build(o, self.kind)
            build(o, context.scene)
        _select_only(context, objs[-1])
        return {"FINISHED"}


class DSMK_OT_opening_add(bpy.types.Operator):
    """Add a window opening at the 3D cursor (a box cut out of the walls; its +Y axis goes through the wall)"""
    bl_idname = "dsmk.opening_add"
    bl_label = "Add Window"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        ob = _new_object(context, "Window", [], [], [])
        ob.rotation_euler = context.scene.cursor.rotation_euler
        with suspended():
            ob.dsmk_build.glass = True
        make_opening(ob, custom=False)
        for w in walls_cut_by(ob):
            build(w, context.scene)
        _select_only(context, ob)
        return {"FINISHED"}


class DSMK_OT_opening_mark(bpy.types.Operator):
    """Use the selected meshes as openings (closed meshes cut out of the walls, not exported)"""
    bl_idname = "dsmk.opening_mark"
    bl_label = "Use as Opening"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = [o for o in context.selected_objects if o.type == "MESH" and role(o) == "NONE"
                and o.dsmk.kind == "NONE"]
        for o in objs:
            make_opening(o, custom=True)
        walls = {w.name: w for o in objs for w in walls_cut_by(o)}
        for w in walls.values():
            build(w, context.scene)
        return {"FINISHED"}


class DSMK_OT_build_edit_outline(bpy.types.Operator):
    """Edit the outline of the active wall or floor (Edit Mode); the wall follows"""
    bl_idname = "dsmk.build_edit_outline"
    bl_label = "Edit Outline"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and role(o) in ("WALL", "FLOOR") and o.dsmk_build.outline is not None

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        o = context.active_object
        ol = o.dsmk_build.outline
        ol.hide_set(False)
        _select_only(context, ol)
        bpy.ops.object.mode_set(mode="EDIT")
        if role(o) == "WALL":
            bpy.ops.mesh.select_mode(type="EDGE")
        return {"FINISHED"}


class DSMK_OT_build_done(bpy.types.Operator):
    """Leave the outline and select its wall or floor again"""
    bl_idname = "dsmk.build_done"
    bl_label = "Done"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and role(o) == "OUTLINE" and o.parent is not None

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        w = context.active_object.parent
        build(w, context.scene)
        _select_only(context, w)
        return {"FINISHED"}


class DSMK_OT_build_rebuild(bpy.types.Operator):
    """Build the selected walls, floors and openings again (all of the scene when nothing is selected)"""
    bl_idname = "dsmk.build_rebuild"
    bl_label = "Rebuild"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        objs = context.selected_objects or list(context.scene.objects)
        for o in objs:
            if role(o) == "OPENING":
                build_opening(o)
        n = 0
        for o in objs:
            if role(o) in ("WALL", "FLOOR"):
                build(o, context.scene)
                n += 1
        self.report({"INFO"}, f"{n} wall(s) and floor(s) built")
        return {"FINISHED"}


class DSMK_OT_build_freeze(bpy.types.Operator):
    """Turn the selected walls and floors into ordinary meshes (their outlines are deleted)"""
    bl_idname = "dsmk.build_freeze"
    bl_label = "Freeze"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for o in list(context.selected_objects):
            if role(o) in ("WALL", "FLOOR"):
                freeze(o)
        return {"FINISHED"}


class DSMK_PT_build(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Deeper Still"
    bl_label = "Walls and Floors"
    bl_idname = "DSMK_PT_build"

    def draw(self, context):
        lay = self.layout
        col = lay.column(align=True)
        row = col.row(align=True)
        row.operator("dsmk.build_add", text="Add Wall", icon="MOD_BUILD").kind = "WALL"
        row.operator("dsmk.build_add", text="Add Floor", icon="MESH_PLANE").kind = "FLOOR"
        row = col.row(align=True)
        row.operator("dsmk.opening_add", icon="MOD_BOOLEAN")
        row.operator("dsmk.opening_mark", icon="SELECT_SUBTRACT")
        o = context.active_object
        r = role(o)
        if r == "NONE":
            lay.label(text="Select a mesh to make it a wall or a floor")
            return
        p = o.dsmk_build
        box = lay.box().column()
        if r == "OUTLINE":
            box.label(text=f"Outline of {o.parent.name if o.parent else '?'}", icon="EDITMODE_HLT")
            box.operator("dsmk.build_done", icon="CHECKMARK")
            return
        if r in ("WALL", "FLOOR"):
            box.label(text="Wall" if r == "WALL" else "Floor", icon="MOD_BUILD")
            if r == "WALL":
                box.prop(p, "height")
                box.prop(p, "thickness")
                box.prop(p, "offset", slider=True)
                box.prop(p, "dark_base")
                sub = box.column()
                sub.enabled = p.dark_base
                sub.prop(p, "dark_height")
            else:
                box.prop(p, "floor_thickness")
            box.prop(p, "use_openings")
            box.prop(p, "uv_tile")
            box.prop(p, "smooth_angle")
            box.label(text="Materials: the outline's material slots")
            row = box.row(align=True)
            row.operator("dsmk.build_edit_outline", icon="EDITMODE_HLT")
            row.operator("dsmk.build_rebuild", text="", icon="FILE_REFRESH")
            row.operator("dsmk.build_freeze", text="", icon="FREEZE")
        elif r == "OPENING":
            box.label(text="Opening (not exported)", icon="MOD_BOOLEAN")
            box.prop(p, "custom_shape")
            sub = box.column()
            sub.enabled = not p.custom_shape
            sub.prop(p, "width")
            sub.prop(p, "opening_height")
            sub.prop(p, "depth")
            box.prop(p, "glass")
            sub = box.column()
            sub.enabled = p.glass
            sub.prop(p, "glass_offset")
            sub.prop(p, "glass_material")


classes = (DSMK_BuildProps, DSMK_OT_build_add, DSMK_OT_opening_add, DSMK_OT_opening_mark,
           DSMK_OT_build_edit_outline, DSMK_OT_build_done, DSMK_OT_build_rebuild, DSMK_OT_build_freeze,
           DSMK_PT_build)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.dsmk_build = PointerProperty(type=DSMK_BuildProps)
    bpy.app.handlers.depsgraph_update_post.append(on_depsgraph)


def unregister():
    if on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph)
    if bpy.app.timers.is_registered(_run_pending):
        bpy.app.timers.unregister(_run_pending)
    del bpy.types.Object.dsmk_build
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
