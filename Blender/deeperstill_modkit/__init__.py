"""Deeper Still Mod Kit: make Deeper Still levels in Blender, play them, share them.

- Finds the installed game (Steam libraries) and extracts its meshes,
  textures and data into a local cache (the kit itself ships no game file).
- Kit objects (Add panel or Shift+A > Deeper Still): player start, hostile
  and peaceful NPCs, patrol points, ladders, air vents, trees, throwable
  objects, doors, end portal, win box, NavMesh zones, win camera.
- Scenery: every visible mesh of the scene, with game materials by name.
- Walls, floors and window openings built from outlines (real geometry
  made by the kit: height, thickness, dark base, openings, UVs).
- Export to a mod folder (never the game folder), Play Here (the game with
  `--mod` and `--level`), Verify (the game's mod verifier), Publish to
  Workshop (after a confirmation).

Documentation: BLENDER_KIT.md (next to the kit in the game's ModdingKit folder).
"""

import bpy
from bpy.app.handlers import persistent
from bpy.props import StringProperty

from . import actors, display, kit, ops, props, ui, walls


class DSMK_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    game_folder: StringProperty(name="Game folder", subtype="DIR_PATH",
                                description="Folder of the installed game (empty: found in the Steam libraries)")
    cache_dir: StringProperty(name="Extracted files", subtype="DIR_PATH",
                              description="Cache of the extracted game files (empty: the kit's user folder)")

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "game_folder")
        col.prop(self, "cache_dir")
        col.label(text=f"Cache in use: {kit.cache_dir()}")


_counts = {}


def _flush():
    for scene in bpy.data.scenes:
        for o in actors.fix_duplicate_names(scene):
            o.name = o.dsmk.ue_name
        walls.fix_copies(scene)
    return None


@persistent
def _on_depsgraph(scene, depsgraph):
    # Copies (Shift+D): new actor names, outside the handler.
    n = len(scene.objects)
    before = _counts.get(scene.name)
    _counts[scene.name] = n
    if before is not None and n > before and not bpy.app.background and not bpy.app.timers.is_registered(_flush):
        bpy.app.timers.register(_flush, first_interval=0.2)


@persistent
def _on_load(_):
    _counts.clear()
    kit.forget_cache()
    if kit.cache() is not None:
        for o in bpy.data.objects:
            if o.dsmk.kind != "NONE" and o.type == "EMPTY" and o.instance_collection is None:
                display.refresh(o)


modules = (props, display, ops, ui, walls)


def register():
    bpy.utils.register_class(DSMK_Preferences)
    for m in modules:
        m.register()
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    bpy.app.handlers.load_post.remove(_on_load)
    bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if bpy.app.timers.is_registered(_flush):
        bpy.app.timers.unregister(_flush)
    kit.unregister()
    for m in reversed(modules):
        m.unregister()
    bpy.utils.unregister_class(DSMK_Preferences)
