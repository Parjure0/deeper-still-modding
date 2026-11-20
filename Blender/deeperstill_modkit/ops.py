"""Operators of the kit (buttons of the Deeper Still panel)."""

import os
import subprocess
import sys
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from . import actors, display, export, game, kit, materials, template
from .props import KINDS

ADDABLE = [k for k in KINDS if k[0] != "NONE"]


def _report_lines(lines):
    for l in lines:
        kit.status(line=l)


# --- Adding objects ----------------------------------------------------------------------

class DSMK_OT_add(bpy.types.Operator):
    """Add a kit object at the 3D cursor"""
    bl_idname = "dsmk.add"
    bl_label = "Add"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(items=ADDABLE)

    @classmethod
    def description(cls, context, props):
        return next((k[2] for k in KINDS if k[0] == props.kind), "")

    def execute(self, context):
        scene = context.scene
        if self.kind == "WINVIEW" and actors.kit_objects(scene, "WINVIEW"):
            obj = actors.kit_objects(scene, "WINVIEW")[0]
        else:
            obj = actors.create(scene, self.kind, scene.cursor.location.copy())
            if self.kind == "WINVIEW" and context.screen is not None:
                # Win camera placed where the 3D view looks from.
                rv3d = next((a.spaces.active.region_3d for a in context.screen.areas if a.type == "VIEW_3D"), None)
                if rv3d is not None:
                    obj.matrix_world = rv3d.view_matrix.inverted()
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class DSMK_OT_add_patrol_point(bpy.types.Operator):
    """Add a patrol point at the 3D cursor to the active hostile NPC's patrol (its behaviour becomes Patrolling)"""
    bl_idname = "dsmk.add_patrol_point"
    bl_label = "New Patrol Point"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.dsmk.kind == "HOSTILE"

    def execute(self, context):
        npc = context.active_object
        pt = actors.create(context.scene, "PATROL", context.scene.cursor.location.copy())
        it = npc.dsmk.patrol.add()
        it.target = pt
        npc.dsmk.state = "NewEnumerator1"
        npc.dsmk.patrol_index = len(npc.dsmk.patrol) - 1
        return {"FINISHED"}


class DSMK_OT_patrol_add_selected(bpy.types.Operator):
    """Add the selected patrol points to the active hostile NPC's patrol (in selection order)"""
    bl_idname = "dsmk.patrol_add_selected"
    bl_label = "Add Selected Points"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.dsmk.kind == "HOSTILE"

    def execute(self, context):
        npc = context.active_object
        for o in context.selected_objects:
            if o.dsmk.kind == "PATROL":
                npc.dsmk.patrol.add().target = o
        return {"FINISHED"}


class DSMK_OT_patrol_remove(bpy.types.Operator):
    """Remove the selected entry of the patrol list (the point itself stays)"""
    bl_idname = "dsmk.patrol_remove"
    bl_label = "Remove"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        p = context.active_object.dsmk
        if 0 <= p.patrol_index < len(p.patrol):
            p.patrol.remove(p.patrol_index)
            p.patrol_index = max(0, p.patrol_index - 1)
        return {"FINISHED"}


class DSMK_OT_patrol_move(bpy.types.Operator):
    """Move the selected entry up or down (the NPC walks the list in order, in a loop)"""
    bl_idname = "dsmk.patrol_move"
    bl_label = "Move"
    bl_options = {"REGISTER", "UNDO"}

    up: BoolProperty()

    def execute(self, context):
        p = context.active_object.dsmk
        i, j = p.patrol_index, p.patrol_index + (-1 if self.up else 1)
        if 0 <= i < len(p.patrol) and 0 <= j < len(p.patrol):
            p.patrol.move(i, j)
            p.patrol_index = j
        return {"FINISHED"}


class DSMK_OT_game_material(bpy.types.Operator):
    """Give a game material to the selected meshes (active material slot)"""
    bl_idname = "dsmk.game_material"
    bl_label = "Game Material"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "material"

    material: EnumProperty(name="Material", items=materials.game_material_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if self.material == "NONE":
            return {"CANCELLED"}
        mat = materials.ensure_material(self.material)
        for o in context.selected_objects:
            if o.type in ("MESH", "CURVE") and o.dsmk.kind == "NONE":
                if not o.material_slots:
                    o.data.materials.append(mat)
                else:
                    o.material_slots[o.active_material_index].material = mat
                # Walls and floors: the materials live on their outline.
                ol = o.dsmk_build.outline if o.dsmk_build.role in ("WALL", "FLOOR") else None
                if ol is not None and ol.type == "MESH":
                    ol.data.materials.clear()
                    for m in o.data.materials:
                        ol.data.materials.append(m)
        return {"FINISHED"}


class DSMK_OT_load_textures(bpy.types.Operator):
    """Show the game's textures on the materials named after game materials (approximate preview)"""
    bl_idname = "dsmk.load_textures"
    bl_label = "Load Game Textures"

    def execute(self, context):
        if kit.cache() is None:
            self.report({"ERROR"}, "Extract the game files first")
            return {"CANCELLED"}
        n = materials.load_all_textures()
        self.report({"INFO"}, f"{n} material(s) with a game texture")
        return {"FINISHED"}


class DSMK_OT_refresh_display(bpy.types.Operator):
    """Build the display models of the kit objects again from the extracted game files"""
    bl_idname = "dsmk.refresh_display"
    bl_label = "Refresh Display"

    def execute(self, context):
        kit.forget_cache()
        if kit.cache() is None:
            self.report({"WARNING"}, "No extracted game files: kit objects show as empties")
        display.refresh_all(rebuild=True)
        return {"FINISHED"}


class DSMK_OT_new_level(bpy.types.Operator):
    """New level scene: Blender units set like the game (1 unit = 1 cm), player start, floor, NavMesh zone"""
    bl_idname = "dsmk.new_level"
    bl_label = "New Level Scene"

    with_template: BoolProperty(name="Template level", default=False,
                                description="Add the template level shipped with the game (or a small commented "
                                            "template level) instead of an empty level")

    def execute(self, context):
        scene = None
        path = template.shipped_template() if self.with_template else None
        if path:
            # The template level shipped with the game (ModdingKit/Blender).
            with bpy.data.libraries.load(path, link=False) as (src, dst):
                dst.scenes = [n for n in src.scenes if n == template.SHIPPED_SCENE][:1]
            scene = dst.scenes[0] if dst.scenes else None
        if scene is None:
            scene = bpy.data.scenes.new("Template" if self.with_template else "MyLevel")
            if self.with_template:
                template.build_template(scene)
            else:
                template.build_empty(scene)
        context.window.scene = scene
        display.refresh_all()
        return {"FINISHED"}


# --- Game ----------------------------------------------------------------------------

class DSMK_OT_find_game(bpy.types.Operator):
    """Look for the installed game in the Steam libraries (or the folder set in the preferences)"""
    bl_idname = "dsmk.find_game"
    bl_label = "Find Game"

    def execute(self, context):
        exe, how = kit.game_exe(refresh=True)
        self.report({"INFO"} if exe else {"ERROR"}, f"{exe} ({how})" if exe else how)
        return {"FINISHED"}


class DSMK_OT_extract(bpy.types.Operator):
    """Extract the game's meshes, textures and data from the installed game into the kit's cache (needed once, and after each game update)"""
    bl_idname = "dsmk.extract"
    bl_label = "Extract Game Files"

    @classmethod
    def poll(cls, context):
        return not kit.STATUS["busy"]

    def execute(self, context):
        exe, how = kit.game_exe()
        if exe is None:
            self.report({"ERROR"}, how)
            return {"CANCELLED"}
        dest = kit.cache_dir()
        kit.status(state="Extracting game files...", busy=True, clear=True)

        def work():
            t0 = time.perf_counter()
            try:
                code, lines = game.extract_assets(exe, dest)
                _report_lines(lines[-15:])
                kit.forget_cache()
                ok = code == 0 and kit.cache() is not None
                kit.status(state=f"Extraction {'done' if ok else 'FAILED'} ({time.perf_counter() - t0:.0f} s)")
                if ok:
                    bpy.app.timers.register(lambda: (display.refresh_all(rebuild=True), None)[1], first_interval=0.1)
            except Exception as e:  # noqa: BLE001 - shown in the panel
                kit.status(state="Extraction FAILED", line=f"ERROR {e}")
            finally:
                kit.status(busy=False)

        kit.run_in_thread(work)
        return {"FINISHED"}


# --- Mod ----------------------------------------------------------------------------

def _do_export(context, op):
    kit.status(state="Export...", busy=True, clear=True)
    try:
        mod_dir = kit.mod_dir(context.scene)
        exe, _ = kit.game_exe()
        if exe and os.path.normcase(os.path.abspath(mod_dir)).startswith(
                os.path.normcase(os.path.dirname(os.path.abspath(exe)))):
            raise ValueError("the mod folder must not be inside the game folder")
        _report, lines = export.export_scene(context, mod_dir, kit.cache(), log=lambda *_: None)
        _report_lines(lines)
        kit.status(state=f"Exported to {mod_dir}", busy=False)
        return mod_dir
    except Exception as e:  # noqa: BLE001 - shown in the panel
        kit.status(state="Export FAILED", line=f"ERROR {e}", busy=False)
        op.report({"ERROR"}, str(e))
        return None


def _bake(exe, mod_dir, map_name):
    """Navigation of the exported level computed by the game and written in the
    mod (navmesh/<level>.nav). Runs in the worker thread."""
    if exe is None:
        kit.status(line="NOTE navigation not computed (game not found): the game computes it when the level loads")
        return False
    kit.status(state="Computing the navigation (NPCs)...")
    t0 = time.time()
    code, lines = game.bake_navmesh(exe, mod_dir, map_name)
    if code == 0:
        kit.status(line=f"Navigation computed in {time.time() - t0:.0f} s (navmesh/{map_name}.nav)")
        return True
    _report_lines([l for l in lines if "ERROR" in l or "panicked" in l][-10:])
    kit.status(line=f"NOTE navigation not computed (code {code}): the game computes it when the level loads")
    return False


class DSMK_OT_export(bpy.types.Operator):
    """Export the scene to the mod folder (level, meshes, collisions, navigation, mod.json)"""
    bl_idname = "dsmk.export"
    bl_label = "Export Mod"

    @classmethod
    def poll(cls, context):
        return not kit.STATUS["busy"]

    def execute(self, context):
        mod_dir = _do_export(context, self)
        if not mod_dir:
            return {"CANCELLED"}
        exe, _ = kit.game_exe()
        map_name = context.scene.dsmk.map_name
        kit.status(busy=True)

        def work():
            try:
                _bake(exe, mod_dir, map_name)
                kit.status(state=f"Exported to {mod_dir}")
            except Exception as e:  # noqa: BLE001 - shown in the panel
                kit.status(state="Navigation FAILED", line=f"ERROR {e}")
            finally:
                kit.status(busy=False)

        kit.run_in_thread(work)
        return {"FINISHED"}


class DSMK_OT_play_here(bpy.types.Operator):
    """Export the scene to the mod folder and play the level in the installed game"""
    bl_idname = "dsmk.play_here"
    bl_label = "Play Here"

    @classmethod
    def poll(cls, context):
        return not kit.STATUS["busy"]

    def execute(self, context):
        exe, how = kit.game_exe()
        if exe is None:
            self.report({"ERROR"}, how)
            return {"CANCELLED"}
        pose = export.start_pose(context, context.scene.dsmk.start)
        mod_dir = _do_export(context, self)
        if mod_dir is None:
            return {"CANCELLED"}
        s = context.scene.dsmk
        map_name, mod_id = s.map_name, s.mod_id
        kit.status(busy=True)

        def work():
            try:
                # Navigation first (written in the mod, copied with it).
                _bake(exe, mod_dir, map_name)
                folder = mod_dir
                if pose is not None:
                    folder = export.playtest_copy(mod_dir, map_name, mod_id, pose)
                    kit.status(line=f"Start moved (play-test copy: {folder})")
                log = os.path.join(game.user_data_dir(), "playtest", "game.log")
                os.makedirs(os.path.dirname(log), exist_ok=True)
                proc = game.play(exe, [folder], map_name, log_path=log)
                kit.status(state=f"Game started (level {map_name})", line=f"Game log: {log} (PID {proc.pid})")
            except Exception as e:  # noqa: BLE001 - shown in the panel
                kit.status(state="Play Here FAILED", line=f"ERROR {e}")
            finally:
                kit.status(busy=False)

        kit.run_in_thread(work)
        return {"FINISHED"}


class DSMK_OT_verify(bpy.types.Operator):
    """Check the mod folder with the game's verifier (one error per line)"""
    bl_idname = "dsmk.verify"
    bl_label = "Verify"

    @classmethod
    def poll(cls, context):
        return not kit.STATUS["busy"]

    def execute(self, context):
        exe, how = kit.game_exe()
        mod_dir = kit.mod_dir(context.scene)
        if exe is None or not mod_dir:
            self.report({"ERROR"}, how if exe is None else "choose a mod folder first")
            return {"CANCELLED"}
        kit.status(state="Verifying...", busy=True, clear=True)

        def work():
            try:
                code, lines = game.verify_mod(exe, mod_dir)
                _report_lines(lines[-40:])
                kit.status(state="Verification OK" if code == 0 else f"Verification: errors (code {code})")
            except Exception as e:  # noqa: BLE001 - shown in the panel
                kit.status(state="Verification FAILED", line=f"ERROR {e}")
            finally:
                kit.status(busy=False)

        kit.run_in_thread(work)
        return {"FINISHED"}


class DSMK_OT_publish(bpy.types.Operator):
    """Publish the mod folder to the Steam Workshop (asks for confirmation first)"""
    bl_idname = "dsmk.publish"
    bl_label = "Publish to Workshop"

    confirm: BoolProperty(name="I own this content and want to upload it to the Steam Workshop", default=False)

    @classmethod
    def poll(cls, context):
        return not kit.STATUS["busy"]

    def invoke(self, context, event):
        self.confirm = False
        return context.window_manager.invoke_props_dialog(self, width=520, title="Publish to Steam Workshop")

    def draw(self, context):
        s = context.scene.dsmk
        col = self.layout.column()
        col.label(text=f"Mod: {s.mod_name} ({s.mod_id}) {s.mod_version}")
        col.label(text=f"Folder: {kit.mod_dir(context.scene)}")
        col.label(text="Run Verify first. The item is created private: change its visibility on Steam.")
        col.label(text="Steam may ask you to accept the Workshop legal agreement.")
        col.prop(self, "confirm")

    def execute(self, context):
        if not self.confirm:
            self.report({"WARNING"}, "Not published (not confirmed)")
            return {"CANCELLED"}
        exe, how = kit.game_exe()
        mod_dir = kit.mod_dir(context.scene)
        if exe is None or not mod_dir or not os.path.isfile(os.path.join(mod_dir, "mod.json")):
            self.report({"ERROR"}, how if exe is None else "export the mod first")
            return {"CANCELLED"}
        kit.status(state="Publishing...", busy=True, clear=True)

        def work():
            try:
                code, lines = game.publish_mod(exe, mod_dir)
                _report_lines(lines[-40:])
                kit.status(state="Published" if code == 0 else f"Publishing FAILED (code {code})")
            except Exception as e:  # noqa: BLE001 - shown in the panel
                kit.status(state="Publishing FAILED", line=f"ERROR {e}")
            finally:
                kit.status(busy=False)

        kit.run_in_thread(work)
        return {"FINISHED"}


class DSMK_OT_open_folder(bpy.types.Operator):
    """Open the mod folder in the file manager"""
    bl_idname = "dsmk.open_folder"
    bl_label = "Open Mod Folder"

    def execute(self, context):
        d = kit.mod_dir(context.scene)
        if not d or not os.path.isdir(d):
            self.report({"ERROR"}, "export the mod first")
            return {"CANCELLED"}
        if sys.platform == "win32":
            os.startfile(d)  # noqa: S606 - user's own folder
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", d])
        return {"FINISHED"}


class DSMK_OT_render_preview(bpy.types.Operator):
    """Render preview.png (Workshop preview and level thumbnail) from the win camera, in the mod folder"""
    bl_idname = "dsmk.render_preview"
    bl_label = "Render Preview"

    def execute(self, context):
        scene = context.scene
        cams = actors.kit_objects(scene, "WINVIEW")
        d = kit.mod_dir(scene)
        if not cams or not d:
            self.report({"ERROR"}, "add a win camera and choose a mod folder first")
            return {"CANCELLED"}
        r = scene.render
        old = (scene.camera, r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath,
               r.image_settings.file_format)
        try:
            scene.camera = cams[0]
            r.engine = "BLENDER_WORKBENCH"
            r.resolution_x, r.resolution_y, r.resolution_percentage = 1280, 720, 100
            r.image_settings.file_format = "PNG"
            os.makedirs(d, exist_ok=True)
            r.filepath = os.path.join(d, "preview.png")
            bpy.ops.render.render(write_still=True)
        finally:
            (scene.camera, r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath,
             r.image_settings.file_format) = old
        self.report({"INFO"}, f"{os.path.join(d, 'preview.png')} written")
        return {"FINISHED"}


classes = (DSMK_OT_add, DSMK_OT_add_patrol_point, DSMK_OT_patrol_add_selected, DSMK_OT_patrol_remove,
           DSMK_OT_patrol_move, DSMK_OT_game_material, DSMK_OT_load_textures, DSMK_OT_refresh_display,
           DSMK_OT_new_level, DSMK_OT_find_game, DSMK_OT_extract, DSMK_OT_export, DSMK_OT_play_here,
           DSMK_OT_verify, DSMK_OT_publish, DSMK_OT_open_folder, DSMK_OT_render_preview)


def menu_add(self, context):
    self.layout.separator()
    self.layout.menu("DSMK_MT_add", icon="EVENT_D")


class DSMK_MT_add(bpy.types.Menu):
    bl_label = "Deeper Still"
    bl_idname = "DSMK_MT_add"

    def draw(self, context):
        for k in ADDABLE:
            self.layout.operator("dsmk.add", text=k[1]).kind = k[0]


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.utils.register_class(DSMK_MT_add)
    bpy.types.VIEW3D_MT_add.append(menu_add)


def unregister():
    bpy.types.VIEW3D_MT_add.remove(menu_add)
    bpy.utils.unregister_class(DSMK_MT_add)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
