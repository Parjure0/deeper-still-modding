"""Properties of the kit objects (Object.dsmk) and of the level scene (Scene.dsmk)."""

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty,
                       StringProperty)

from . import gamedata as gd

KINDS = (
    ("NONE", "None", "Ordinary object (scenery when it is a mesh)", 0),
    ("PLAYERSTART", "Player Start", "Where the player starts", 1),
    ("HOSTILE", "Hostile NPC", "Enemy (type, weapon, starting behaviour, patrol)", 2),
    ("PEACEFUL", "Peaceful NPC", "Civilian", 3),
    ("PATROL", "Patrol Point", "Point of a hostile NPC's patrol", 4),
    ("LADDER", "Ladder", "Ladder (rungs every 35 cm)", 5),
    ("AIRVENT", "Air Vent", "Air vent of the Air Vent ability", 6),
    ("TREE", "Tree", "Tree of the game", 7),
    ("THROWABLE", "Throwable Object", "Object the player can pick up and throw", 8),
    ("DOOR", "Door", "Swinging door (pushed open by the player, by shots, torn off by a headbutt)", 9),
    ("END_PORTAL", "End Portal", "The level is won when the player enters it", 10),
    ("WON_BOX", "Win Box", "Closed box where the winner is moved when the level is won: keep it away from the level", 11),
    ("NAVMESH", "NavMesh Zone", "NPCs can only walk inside the NavMesh zones", 12),
    ("WINVIEW", "Win Camera", "View of the end of the level when no NPC was killed", 13),
    ("PLAY_AREA", "Play Area", "Out of bounds limit: the player is out of bounds where no Play Area face is above "
     "them (up to 400 m). Invisible in the game", 14),
)
KIND_LABEL = {k[0]: k[1] for k in KINDS}
# Kit kinds that are copies of a game actor (class of the copied actor).
KIND_CLASS = {"PLAYERSTART": gd.CLASS_PLAYERSTART, "HOSTILE": gd.CLASS_HOSTILE, "PEACEFUL": gd.CLASS_PEACEFUL,
              "PATROL": gd.CLASS_PATROL, "LADDER": gd.CLASS_LADDER, "AIRVENT": gd.CLASS_AIRVENT,
              "TREE": gd.CLASS_TREE, "THROWABLE": gd.CLASS_THROWABLE, "DOOR": gd.CLASS_DOOR,
              "END_PORTAL": gd.CLASS_END_PORTAL, "WON_BOX": gd.CLASS_WON_BOX, "WINVIEW": gd.CLASS_WINVIEW}
# Name of the actors made by the kit (`<prefix>_<n>`).
NAME_PREFIX = {"PLAYERSTART": "PlayerStart", "HOSTILE": "HostileNPC", "PEACEFUL": "PeacefulNPC",
               "PATROL": "PatrolPoint", "LADDER": "Ladder", "AIRVENT": "AirVent", "TREE": "Tree",
               "THROWABLE": "Throwable", "DOOR": "Door", "END_PORTAL": "EndPortal", "WON_BOX": "WinBox",
               "NAVMESH": "NavMeshZone", "WINVIEW": "WinCamera", "PLAY_AREA": "PlayArea"}


def _refresh(self, context):
    obj = self.id_data
    if isinstance(obj, bpy.types.Object):
        from . import display
        display.refresh(obj)


def _type_changed(self, context):
    """Woman / FatWoman: hair on by default (ChooseHairHat), off otherwise."""
    if self.kind == "HOSTILE":
        self.hair = self.enemy in gd.WOMAN_ENEMIES
    elif self.kind == "PEACEFUL":
        self.hair = self.peaceful_type in gd.WOMAN_PEACEFUL
    _refresh(self, context)


def _stop_changed(self, context):
    """Stop? and RotateCharacter? go together (as in the game's levels)."""
    self.rotate_character = self.stop
    _refresh(self, context)


def poll_patrol(self, obj):
    return obj.dsmk.kind == "PATROL"


class DSMK_PatrolItem(bpy.types.PropertyGroup):
    target: PointerProperty(name="Point", type=bpy.types.Object, poll=poll_patrol)


class DSMK_ObjectProps(bpy.types.PropertyGroup):
    kind: EnumProperty(name="Kind", items=KINDS, default="NONE", update=_refresh)
    ue_name: StringProperty(name="Actor name", description="Name of the actor in the game level (unique)")
    # Hostile NPC
    enemy: EnumProperty(name="Type", items=[(e[0], e[1], "") for e in gd.ENEMY_TYPES], default=gd.DEFAULT_ENEMY,
                        update=_type_changed)
    weapon: EnumProperty(name="Weapon", items=[(w[0], w[1], "") for w in gd.WEAPON_TYPES], default=gd.DEFAULT_WEAPON,
                         update=_refresh)
    state: EnumProperty(name="Behaviour", items=gd.START_STATES, default=gd.DEFAULT_STATE)
    patrol: CollectionProperty(type=DSMK_PatrolItem)
    patrol_index: IntProperty()
    hair: BoolProperty(name="Hair", description="Hair (woman hair mesh of the game)", update=_refresh)
    # Peaceful NPC
    peaceful_type: EnumProperty(name="Type", items=[(t, t, "") for t in gd.PEACEFUL_TYPES],
                                default=gd.DEFAULT_PEACEFUL_TYPE, update=_type_changed)
    start_static: BoolProperty(name="Static", description="Stays in place (StartStatic?)")
    cant_panic: BoolProperty(name="Can't panic", description="Never panics (CantPanic?)")
    # Patrol point
    stop: BoolProperty(name="Stop", description="The NPC stops and turns to the point's direction (+X)",
                       default=gd.DEFAULT_STOP, update=_stop_changed)
    rotate_character: BoolProperty(default=gd.DEFAULT_ROTATE)
    # Ladder
    ladder_count: IntProperty(name="Rungs", description="Number of rungs (35 cm each)", default=5, min=1, max=200,
                              update=_refresh)
    two_sided: BoolProperty(name="Two-sided", description="Climbable from both sides", update=_refresh)
    # Tree, throwable object
    tree: EnumProperty(name="Tree", items=[(t[0], t[0], "") for t in gd.TREES], default=gd.DEFAULT_TREE,
                       update=_refresh)
    throwable: EnumProperty(name="Mesh", items=[(t[0], t[1], "") for t in gd.THROWABLES],
                            default=gd.DEFAULT_THROWABLE, update=_refresh)


def _level_search(self, context, edit_text):
    from . import kit
    return [n for n in kit.level_names() if edit_text.lower() in n.lower()]


START_MODES = (
    ("PLAYERSTART", "Player Start", "Start at the scene's player start"),
    ("VIEW", "3D View", "Start under the point of view of the 3D view, looking the same way"),
    ("CURSOR", "3D Cursor", "Start under the 3D cursor, facing its X axis"),
)


class DSMK_SceneProps(bpy.types.PropertyGroup):
    mod_dir: StringProperty(name="Mod folder", subtype="DIR_PATH",
                            description="Folder of the mod (created by the export). Never the game folder")
    mod_id: StringProperty(name="Mod id", description="Short unique id of the mod: lowercase letters, digits, _ - .",
                           default="my_first_mod")
    mod_name: StringProperty(name="Mod name", description="Name of the mod (Mods screen, Workshop)",
                             default="My First Mod")
    mod_version: StringProperty(name="Version", default="1.0.0")
    description: StringProperty(name="Description", description="Description of the mod (Workshop page)")
    map_name: StringProperty(name="Level name", description="Name of the level file (letters, digits, _)",
                             default="MyLevel")
    level_title: StringProperty(name="Level title", description="Title of the level in the game's level list",
                                default="My Level")
    base_level: StringProperty(name="Base level", default="LVL_03", search=_level_search,
                               description="Game level whose music, fog, sky and post-process the level uses")
    start: EnumProperty(name="Start", items=START_MODES, default="PLAYERSTART",
                        description="Where the player starts with Play Here")


classes = (DSMK_PatrolItem, DSMK_ObjectProps, DSMK_SceneProps)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.dsmk = PointerProperty(type=DSMK_ObjectProps)
    bpy.types.Scene.dsmk = PointerProperty(type=DSMK_SceneProps)


def unregister():
    del bpy.types.Scene.dsmk
    del bpy.types.Object.dsmk
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
