"""Deeper Still panel (3D view sidebar, N key)."""

import os

import bpy

from . import game, kit
from .props import KIND_LABEL

ADD_ROWS = (("PLAYERSTART", "END_PORTAL"), ("HOSTILE", "PEACEFUL"), ("PATROL", "LADDER"), ("DOOR", "AIRVENT"),
            ("TREE", "THROWABLE"), ("NAVMESH", "WINVIEW"), ("WON_BOX", "PLAY_AREA"))


def _wrap(context, text, margin=40):
    width = max(20, int((context.region.width - margin) / 7)) if context.region else 60
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    return lines + ([cur] if cur else [])


class DSMK_UL_patrol(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"{index + 1}.")
        row.prop(item, "target", text="")


class _Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Deeper Still"


class DSMK_PT_game(_Base, bpy.types.Panel):
    bl_label = "Game"
    bl_idname = "DSMK_PT_game"

    def draw(self, context):
        col = self.layout.column()
        exe, how = kit.game_exe()
        if exe:
            col.label(text=os.path.dirname(exe), icon="CHECKMARK")
        else:
            for i, l in enumerate(_wrap(context, how)):
                col.label(text=l, icon="ERROR" if i == 0 else "BLANK1")
        col.operator("dsmk.find_game", icon="VIEWZOOM")
        state = game.cache_state(kit.cache_dir(), exe)
        icon = {"ok": "CHECKMARK", "outdated": "ERROR", "missing": "ERROR"}[state]
        text = {"ok": "Game files extracted", "outdated": "Game updated: extract again",
                "missing": "Game files not extracted"}[state]
        col.label(text=text, icon=icon)
        col.operator("dsmk.extract", icon="IMPORT")
        row = col.row(align=True)
        row.operator("dsmk.refresh_display", icon="FILE_REFRESH")
        row.operator("dsmk.load_textures", icon="TEXTURE")


class DSMK_PT_mod(_Base, bpy.types.Panel):
    bl_label = "Mod and Level"
    bl_idname = "DSMK_PT_mod"

    def draw(self, context):
        s = context.scene.dsmk
        col = self.layout.column()
        col.prop(s, "mod_dir")
        col.prop(s, "mod_id")
        col.prop(s, "mod_name")
        col.prop(s, "mod_version")
        col.prop(s, "description")
        col.separator()
        col.prop(s, "map_name")
        col.prop(s, "level_title")
        col.prop(s, "base_level")
        row = col.row(align=True)
        row.operator("dsmk.new_level", text="New Level", icon="SCENE_DATA").with_template = False
        row.operator("dsmk.new_level", text="New Template", icon="FILE_BLEND").with_template = True


class DSMK_PT_add(_Base, bpy.types.Panel):
    bl_label = "Add"
    bl_idname = "DSMK_PT_add"

    def draw(self, context):
        col = self.layout.column(align=True)
        for r in ADD_ROWS:
            row = col.row(align=True)
            for k in r:
                row.operator("dsmk.add", text=KIND_LABEL[k]).kind = k
        self.layout.operator("dsmk.game_material", icon="MATERIAL")


class DSMK_PT_object(_Base, bpy.types.Panel):
    bl_label = "Active Object"
    bl_idname = "DSMK_PT_object"

    def draw(self, context):
        o = context.active_object
        col = self.layout.column()
        if o is None:
            col.label(text="No active object")
            return
        p = o.dsmk
        if p.kind == "NONE":
            if o.type in ("MESH", "CURVE"):
                col.label(text="Scenery (exported as a static mesh)", icon="MESH_DATA")
                for s in o.material_slots:
                    c = kit.cache()
                    found = c is not None and s.material is not None and c.catalog().find(s.material.name)
                    col.label(text=s.material.name if s.material else "(no material)",
                              icon="CHECKMARK" if found else "ERROR")
            else:
                col.label(text="Not exported")
            return
        col.label(text=KIND_LABEL[p.kind], icon="OUTLINER_OB_EMPTY")
        col.prop(p, "ue_name")
        if p.kind == "HOSTILE":
            col.prop(p, "enemy")
            from . import gamedata as gd
            sub = col.column()
            sub.enabled = not gd.is_melee(p.enemy)
            sub.prop(p, "weapon")
            col.prop(p, "hair")
            col.prop(p, "state")
            if p.state == gd.STATE_PATROLLING:
                col.label(text="Patrol (walked in order, in a loop):")
                row = col.row()
                row.template_list("DSMK_UL_patrol", "", p, "patrol", p, "patrol_index", rows=3)
                side = row.column(align=True)
                side.operator("dsmk.patrol_move", text="", icon="TRIA_UP").up = True
                side.operator("dsmk.patrol_move", text="", icon="TRIA_DOWN").up = False
                side.operator("dsmk.patrol_remove", text="", icon="X")
                r2 = col.row(align=True)
                r2.operator("dsmk.add_patrol_point", icon="ADD")
                r2.operator("dsmk.patrol_add_selected", icon="RESTRICT_SELECT_OFF")
        elif p.kind == "PEACEFUL":
            col.prop(p, "peaceful_type")
            col.prop(p, "hair")
            col.prop(p, "start_static")
            col.prop(p, "cant_panic")
        elif p.kind == "PATROL":
            col.prop(p, "stop")
        elif p.kind == "LADDER":
            col.prop(p, "ladder_count")
            col.prop(p, "two_sided")
            col.label(text=f"Height: {p.ladder_count * 35} cm (climb side: +X)")
        elif p.kind == "TREE":
            col.prop(p, "tree")
        elif p.kind == "THROWABLE":
            col.prop(p, "throwable")
        elif p.kind == "NAVMESH":
            col.label(text="Scale it to cover where NPCs walk")
        elif p.kind == "PLAY_AREA":
            col.label(text="Out of bounds where none of its faces is above the player")
            col.label(text="(up to 400 m above). Edit its faces in Edit Mode")
        elif p.kind == "WINVIEW":
            col.label(text="Field of view: 100° horizontal (as in the game)")


class DSMK_PT_play(_Base, bpy.types.Panel):
    bl_label = "Play and Publish"
    bl_idname = "DSMK_PT_play"

    def draw(self, context):
        s = context.scene.dsmk
        col = self.layout.column()
        col.prop(s, "start")
        row = col.row(align=True)
        row.scale_y = 1.4
        row.operator("dsmk.play_here", icon="PLAY")
        row.operator("dsmk.verify", icon="CHECKBOX_HLT")
        row = col.row(align=True)
        row.operator("dsmk.export", icon="EXPORT")
        row.operator("dsmk.open_folder", text="", icon="FILE_FOLDER")
        row.operator("dsmk.render_preview", text="", icon="RENDER_STILL")
        col.separator()
        col.operator("dsmk.publish", icon="WORLD")
        state, lines, busy = kit.status_copy()
        if state:
            col.label(text=state, icon="TIME" if busy else "INFO")
        if lines:
            box = col.box().column(align=True)
            box.scale_y = 0.75
            for l in lines:
                icon = "ERROR" if l.startswith(("ERROR", "PROBLEM")) else "NONE"
                for i, part in enumerate(_wrap(context, l, 60)):
                    box.label(text=part, icon=icon if i == 0 else "BLANK1")


classes = (DSMK_UL_patrol, DSMK_PT_game, DSMK_PT_mod, DSMK_PT_add, DSMK_PT_object, DSMK_PT_play)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
