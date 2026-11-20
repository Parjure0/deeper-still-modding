"""Game materials in Blender.

A Blender material becomes a game material at the export when it has the
same name (`Concrete`, `Concrete.001` -> the game's Concrete). The kit can
create such materials and show the game's texture on them (approximate
preview: most game materials are projected along the world axes).
"""

import bpy

from . import kit

TEX_NODE = "DSMK_GameTexture"
TILE_CM = 400.0  # preview: one texture tile every 4 m


def game_material_items(self, context):
    c = kit.cache()
    if c is None:
        return [("NONE", "(extract the game files first)", "")]
    items = [(short, short, full) for short, full in c.catalog().names()]
    _ITEMS[:] = items  # Blender needs the list kept alive
    return _ITEMS


_ITEMS = []


def preview_texture(mat, image_path):
    """World-projected image texture on `mat` (replaces a previous preview)."""
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return False
    for n in [n for n in nt.nodes if n.name.startswith(TEX_NODE)]:
        nt.nodes.remove(n)
    img = bpy.data.images.load(image_path, check_existing=True)
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    geo.name = TEX_NODE + "_Geometry"
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.name = TEX_NODE + "_Mapping"
    mapping.inputs["Scale"].default_value = (1.0 / TILE_CM,) * 3
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.name = TEX_NODE
    tex.image = img
    tex.projection = "BOX"
    tex.projection_blend = 0.2
    geo.location, mapping.location, tex.location = (-900, 300), (-700, 300), (-450, 300)
    nt.links.new(geo.outputs["Position"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return True


def ensure_material(short):
    """Blender material named after a game material (texture preview when available)."""
    mat = bpy.data.materials.get(short) or bpy.data.materials.new(short)
    load_texture(mat)
    return mat


def load_texture(mat):
    c = kit.cache()
    if c is None:
        return False
    cat = c.catalog()
    full = cat.find(mat.name)
    if full is None:
        return False
    path = cat.base_color_texture(full)
    return bool(path) and preview_texture(mat, path)


def load_all_textures():
    """Texture preview on every Blender material named after a game material."""
    n = 0
    for mat in bpy.data.materials:
        if mat.name.startswith("DSMK_") or mat.library is not None:
            continue
        if load_texture(mat):
            n += 1
    return n
