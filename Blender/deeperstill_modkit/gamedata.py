"""Game data read from the extracted cache (`--extraire-assets`).

Pure Python (no bpy). The cache has the shipped layout of the game files:
- `paths.txt`: one line per file, "<path used in the data> TAB <file>";
  the first column is the path written inside the game's JSON files
  (e.g. `meshes/user/Scene/_Common/mesh_Cube.glb`), the second the file
  of the cache (e.g. `meshes/Scene/_Common/Cube.glb`);
- `levels/<LEVEL>.json`: the game levels (actors, meshes);
- `materials/index.json`, `textures/registry.json`: materials and textures.

A mod folder has the same layout. Files a mod adds (its level, its meshes)
are not in `paths.txt`: the game reads them under their own path, so the
kit uses the same path inside the data and on disk.

Names written in the game data use the shipped names below (class names,
references). The game turns some words of the data into internal names
when it reads them (`RESERVED`): names made by the kit never contain them
(`safe_name`, `safe_path`).
"""

import json
import os
import re

# --- Shipped names ------------------------------------------------------------------

CLASS_PATROL = "actor_PatrollingLocation-class"
CLASS_PEACEFUL = "actor_PeacefulNPC-class"
CLASS_HOSTILE = "actor_HostileNPC-class"
CLASS_PLAYERSTART = "PlayerStart"
CLASS_TREE = "actor_Tree-class"
CLASS_LADDER = "actor_Ladder-class"
CLASS_AIRVENT = "actor_AirVent-class"
CLASS_THROWABLE = "actor_ThrowableObject-class"
CLASS_WINVIEW = "actor_WinView-class"
CLASS_DOOR = "actor_Door-class"
CLASS_END_PORTAL = "actor_EndPortal-class"
CLASS_WON_BOX = "actor_WonBox-class"
CLASS_LEVEL_SCRIPT = "actor_CustomLevelLogic-class"
CLASS_SKY = "actor_Skysphere-class"
CLASS_NAV_DATA = "WalkMesh"
CLASS_POST_PROCESS = "PostProcessVolume"
CLASS_NAV_BOUNDS = "NavMeshBoundsVolume"
CLASS_STATIC_ACTOR = "FixedMeshActor"
CLASS_STATIC_COMPONENT = "FixedMeshComponent"
STATIC_COMPONENT_NAME = "FixedMeshComponent0"   # component of a static mesh actor
STATIC_MESH_PROP = "FixedMesh"                # its mesh property

# Actors of a level that are not placed by the kit: copied from the "base
# level" (level script with music and fog, sky, post-process, navigation data).
BASE_CLASSES = (CLASS_LEVEL_SCRIPT, CLASS_SKY, CLASS_POST_PROCESS, CLASS_NAV_DATA, CLASS_WON_BOX, CLASS_WINVIEW)
# Properties of the level script that point to actors of the base level only.
BASE_SCRIPT_DROP = ("collider_Water",)

MODEL_REF = "\"@core.Model'Model_1'\""
BODY_SETUP_REF = "\"@core.BodySetup'BodySetup_0'\""
CUBE_BUILDER_REF = "\"@editor.CubeBuilder'CubeBuilder_1'\""
TRACE_COMPLEX = "collide_UseComplexAsSimple"
LADDER_HISM = "HierarchicalInstancedFixedMesh"
WEAPON_COMPONENT = "mesh_Weapon"
# Fallback material (owner's grey blockout) for a Blender material unknown to the game.
FALLBACK_MATERIAL = "@/Logics/mat_Blockout.mat_Blockout"

# Out of bounds limit (play area): invisible mesh that only blocks the
# OutOfBounds trace channel, like the out of bounds mesh of the game levels
# (the player is out of bounds when nothing of it is above them).
OUT_OF_BOUNDS_FOLDER = "Scene/OutOfBounds"
OUT_OF_BOUNDS_BODY = {"profile": "Custom", "responses": {
    "WorldStatic": "Ignore", "WorldDynamic": "Ignore", "Pawn": "Ignore", "Visibility": "Ignore", "Camera": "Ignore",
    "PhysicsBody": "Ignore", "Vehicle": "Ignore", "Destructible": "Ignore", "BloodDrop": "Ignore",
    "Interact": "Ignore", "Ragdoll": "Ignore", "NPCVisibility": "Ignore", "OutOfBounds": "Block",
    "Bullet": "Ignore"}}

PATROL_REF = "\"@/Characters/PatrollingLocation/actor_PatrollingLocation.actor_PatrollingLocation-class'{}'\""
PEACEFUL_MESH = "\"@core.RiggedMesh'@/Characters/Humanoid/{t}/skin_Humanoid{t}.skin_Humanoid{t}'\""
HAIR_WOMAN = "\"@core.FixedMesh'@/Characters/Humanoid/Woman/mesh_HumanoidWomanHair.mesh_HumanoidWomanHair'\""
STATIC_MESH_REF = "\"@core.FixedMesh'{}'\""
TREES = (
    ("Spruce", "@/Scene/Level_01/Vegetation/mesh_Spruce.mesh_Spruce"),
    ("PlaneTree", "@/Scene/Level_02/PlaneTree/mesh_PlaneTree.mesh_PlaneTree"),
    ("WeepingWillow", "@/Scene/Level_06/Prop/mesh_WeepingWillow.mesh_WeepingWillow"),
)
TREE_PATH = dict(TREES)
DEFAULT_TREE = "Spruce"
THROWABLES = (("WoodenBox", "Wooden box", "@/Scene/_Common/mesh_WoodenBox.mesh_WoodenBox"),)
DEFAULT_THROWABLE = "WoodenBox"

# Words the game turns into internal names when it reads a text file
# (shipped name table of the game): never in a name made by the kit.
RESERVED = ('@/', '@game/', '@base/', '@core.', '@soundgraph.', '@nav.', '@object.', '@editor.', '@ui.',
            '@cutscene.', '@code/', '@types.Vec2f', '@types.', '@types', '/user/', '/soundgraphs/', 'lib:',
            'BaseMaterials', 'BaseSounds', 'BaseFonts', 'BaseTraceChannel', 'Core::', 'Core.', 'SoundGraph',
            'Soundgraph', 'Logic', 'GraphNode', 'MainLevel', 'FixedMesh', 'RiggedMesh', 'AudioClip', 'AudioBus',
            'AudioCue', 'MaterialPreset', 'MaterialRuntime', 'MaterialVariant', 'MaterialSnippet', 'RenderCanvas',
            'Bitmap2D', 'Cutscene', 'FilmScene', 'DataSheet', 'ClipAsset', 'AnimClip', 'AnimAction', 'WalkMesh',
            '@source', 'Oldactor_', '_genvar_actor_', 'boundevent__actor_', '_genvar_', 'boundevent__', 'actor_',
            'part_', 'group_', 'animlogic_', 'widget_', '-class', 'mesh_', 'collider_', 'skeleton_', 'skin_',
            'soundgraph_', 'mat_', 'matvar_', 'matfunc_', 'params_', 'pic_', 'canvas_', 'sheet_', 'struct_', 'enum_',
            'font_', 'fontface_', 'action_', 'controls_', 'clip_', 'bus_', 'mix_', 'concur_', 'atten_', 'cutscene_',
            'ragdoll_', 'anim_', 'animaction_', 'timeline_', 'angular_', 'blending_', 'collide_', 'standon_',
            'domain_', 'lightmodel_', 'scenetex_', 'extrap_', 'interp_', 'slope_Custom', 'slope_', 'sampling_',
            'compress_', 'tickgroup_', 'mipgen_')

# --- Actor data of the game (enumerations and defaults) ----------------------------------------

PLAYERSTART_HALF_HEIGHT = 92.0   # capsule half height (cm): actor = feet + this
PEACEFUL_HALF_HEIGHT = 83.0
LADDER_STEP = 35.0               # one rung every 35 cm
AIRVENT_OFFSET_Z = 110.0

# Enemy types (enum_Enemies): (internal value, display name, capsule half height in cm, melee)
ENEMY_TYPES = (
    ("NewEnumerator0", "HumanoidMen", 83.0, False),
    ("NewEnumerator1", "HumanoidWoman", 83.0, False),
    ("NewEnumerator8", "HumanoidFatMen", 83.0, False),
    ("NewEnumerator9", "HumanoidFatWoman", 83.0, False),
    ("NewEnumerator10", "Kamikaze", 83.0, True),
    ("NewEnumerator2", "SpiderMens", 40.0, True),
    ("NewEnumerator6", "BrainInVat", 57.0, False),
    ("NewEnumerator7", "Bull", 110.0, True),
    ("NewEnumerator11", "NewBeautyStandard", 71.0, True),
)
ENEMY = {e[0]: e for e in ENEMY_TYPES}
WOMAN_ENEMIES = {"NewEnumerator1", "NewEnumerator9"}
# Weapons (enum_Weapon): (internal value, display name)
WEAPON_TYPES = (
    ("NewEnumerator6", "FN Five-seveN"),
    ("NewEnumerator0", "Desert Eagle"),
    ("NewEnumerator10", "Steyr TMP"),
    ("NewEnumerator3", "FAMAS"),
    ("NewEnumerator2", "Street Sweeper"),
    ("NewEnumerator4", "FR-F2"),
    ("NewEnumerator1", "Browning M2"),
    ("NewEnumerator5", "RPG-7"),
    ("NewEnumerator7", "M32"),
)
WEAPON = dict(WEAPON_TYPES)
# Starting states of a hostile NPC (enum_HostileBehaviouralState).
START_STATES = (
    ("NewEnumerator0", "Static", "Stays in place until it sees the player"),
    ("NewEnumerator1", "Patrolling", "Walks through its patrol points, in a loop"),
    ("NewEnumerator7", "MovingRandomly", "Wanders around"),
)
STATE_PATROLLING = "NewEnumerator1"
PEACEFUL_TYPES = ("Men", "Woman", "FatMen", "FatWoman")
WOMAN_PEACEFUL = {"Woman", "FatWoman"}

DEFAULT_ENEMY = "NewEnumerator0"
DEFAULT_WEAPON = "NewEnumerator6"
DEFAULT_STATE = "NewEnumerator0"
DEFAULT_PEACEFUL_TYPE = "Men"
DEFAULT_STOP = True
DEFAULT_ROTATE = False

FOLDERS = {
    CLASS_PATROL: "NPC/PatrollingLocation", CLASS_PEACEFUL: "NPC/Peaceful", CLASS_HOSTILE: "NPC/Hostile",
    CLASS_PLAYERSTART: "PlayerStart", CLASS_TREE: "Scene/Tree", CLASS_LADDER: "Scene/Ladder",
    CLASS_AIRVENT: "Scene/AirVent", CLASS_THROWABLE: "Scene/WoodenBox", CLASS_WINVIEW: "Scene/EndLevelMenu",
    CLASS_DOOR: "Scene/Door", CLASS_END_PORTAL: "Scene/EndPortal", CLASS_WON_BOX: "Scene/EndLevelMenu",
}


def is_melee(enemy):
    return ENEMY.get(enemy, ENEMY[DEFAULT_ENEMY])[3]


def fmt_float(v):
    return f"{v:.6f}"


# --- Safe names ---------------------------------------------------------------------

def _flip_first_letter(s, start, end):
    for i in range(start, end):
        c = s[i]
        if c.isalpha():
            return s[:i] + (c.lower() if c.isupper() else c.upper()) + s[i + 1:]
    return None


def make_safe(s):
    """`s` with every reserved word broken (case of one letter changed)."""
    for _ in range(64):
        hit = None
        for w in RESERVED:
            i = s.find(w)
            if i >= 0 and (hit is None or i < hit[0]):
                hit = (i, w)
        if hit is None:
            return s
        flipped = _flip_first_letter(s, hit[0], hit[0] + len(hit[1]))
        if flipped is None:
            s = s[:hit[0]] + s[hit[0] + len(hit[1]):]
        else:
            s = flipped
    return s


def safe_name(s, fallback="Object"):
    """Identifier for a name made from a Blender name: letters, digits and _,
    without reserved words."""
    s = re.sub(r"[^A-Za-z0-9_]", "_", s or "").strip("_") or fallback
    if s[0].isdigit():
        s = "_" + s
    # Also safe as a folder name inside a path (`/user/`...).
    return make_safe("/" + make_safe(s) + "/")[1:-1]


def is_safe(s):
    return not any(w in s for w in RESERVED)


# --- Cache -------------------------------------------------------------------------------

class Cache:
    """Extracted game files (read only)."""

    def __init__(self, root):
        self.root = os.path.normpath(root)
        # The table may sit in the folder itself or in an `assets` subfolder.
        if not os.path.isfile(os.path.join(self.root, "paths.txt")) and \
                os.path.isfile(os.path.join(self.root, "assets", "paths.txt")):
            self.root = os.path.join(self.root, "assets")
        self.table = {}
        try:
            with open(os.path.join(self.root, "paths.txt"), encoding="utf-8") as f:
                for line in f:
                    if line.startswith("#") or "\t" not in line:
                        continue
                    cols = line.rstrip("\n").split("\t")
                    self.table[cols[0]] = cols[1]
        except OSError:
            pass
        self._json = {}
        self._catalog = None

    def ok(self):
        return bool(self.table) and os.path.isdir(os.path.join(self.root, "levels"))

    def file(self, data_path):
        """File of the cache for a path written in the game data (None if missing)."""
        rel = self.table.get(data_path, data_path)
        p = os.path.join(self.root, *rel.split("/"))
        return p if os.path.isfile(p) else None

    def load_json(self, data_path):
        p = self.file(data_path)
        if p is None:
            raise FileNotFoundError(data_path)
        st = os.stat(p)
        key = (st.st_mtime_ns, st.st_size)
        hit = self._json.get(p)
        if hit is None or hit[0] != key:
            with open(p, encoding="utf-8") as f:
                hit = self._json[p] = (key, json.load(f))
        return hit[1]

    # Levels ------------------------------------------------------------------

    def level_names(self):
        """Game levels (LVL_*), sorted."""
        names = set()
        for k in self.table:
            m = re.fullmatch(r"levels/user/Maps/(LVL_[A-Za-z0-9_]+)\.json", k)
            if m:
                names.add(m.group(1))
        if not names:
            try:
                names = {os.path.splitext(n)[0] for n in os.listdir(os.path.join(self.root, "levels"))
                         if n.startswith("LVL_") and n.endswith(".json")}
            except OSError:
                pass
        return sorted(names)

    def level(self, name):
        return self.load_json(f"levels/user/Maps/{name}.json")

    # Materials ---------------------------------------------------------------

    def catalog(self):
        if self._catalog is None:
            self._catalog = Catalog(self)
        return self._catalog


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


class Catalog:
    """Game materials by short name (`Concrete` for `.../mat_Concrete.mat_Concrete`)."""

    def __init__(self, cache):
        self.cache = cache
        try:
            index = cache.load_json("materials/index.json")
        except (OSError, ValueError):
            index = {}
        # Only the materials shipped with the game (the index also lists
        # materials the game never loads, left out of the installed files).
        self.index = {full: rel for full, rel in index.items() if isinstance(rel, str) and cache.file(rel)}
        self.unshipped = set(index) - set(self.index)
        try:
            self.textures = cache.load_json("textures/registry.json")
        except (OSError, ValueError):
            self.textures = {}
        self.by_norm = {}
        for full in self.index:
            short = full.rsplit(".", 1)[-1]
            self.by_norm.setdefault(_norm(re.sub(r"^(mat|matvar)_", "", short)), []).append(full)

    @staticmethod
    def short(full):
        return re.sub(r"^(mat|matvar)_", "", full.rsplit(".", 1)[-1])

    def names(self):
        """(short name, full name) of every surface material, sorted."""
        out = {}
        for full in self.index:
            if "/_Old/" in full or "/_Marketing/" in full:
                continue
            out.setdefault(self.short(full), full)
        return sorted(out.items(), key=lambda x: x[0].lower())

    def find(self, blender_name):
        base = re.sub(r"\.\d{3}$", "", blender_name)
        cands = self.by_norm.get(_norm(base), [])
        if not cands:
            return None
        return sorted(cands, key=lambda f: ("/_Old/" in f, "/_Marketing/" in f, f))[0]

    def base_color_texture(self, full):
        """Cache file of the first texture of a material (for display in Blender), or None."""
        try:
            mat = self.cache.load_json(self.index[full])
        except (KeyError, OSError, ValueError):
            return None
        for t in mat.get("textures") or []:
            info = self.textures.get(t.get("texture")) or {}
            rel = info.get("file")
            if rel:
                p = self.cache.file(rel)
                if p:
                    return p
        return None


# --- Templates (actors copied from the game levels) ------------------------------------

def strip(v):
    return v.strip('"') if isinstance(v, str) else v


def compat_key(cls, props):
    """What changes the components / meshes of an actor (same rule as the
    game's own level tools): actors with the same key look the same."""
    p = {k: strip(v) for k, v in (props or {}).items()}
    if cls == CLASS_HOSTILE:
        enemy = p.get("E Enemies", DEFAULT_ENEMY)
        weapon = "-" if is_melee(enemy) else p.get("SelectWeapon", DEFAULT_WEAPON)
        return (enemy, weapon, bool(p.get("ChooseHairHat")))
    if cls == CLASS_PEACEFUL:
        return (p.get("ChooseMesh") or "", bool(p.get("ChooseHairHat")))
    if cls == CLASS_PATROL:
        return (str(p.get("Stop?", "True")).lower(),)
    if cls == CLASS_TREE:
        return (p.get("SelectTree") or "",)
    if cls == CLASS_LADDER:
        return (p.get("Count", "0"), p.get("TwoSided?", "False"))
    if cls == CLASS_THROWABLE:
        return (p.get("Mesh") or "",)
    return ()


def template_levels(cache, first=None):
    names = cache.level_names()
    if first in names:
        names.remove(first)
        names.insert(0, first)
    return names


def find_template(cache, cls, key=None, first=None):
    """(level, actor name) of the first game actor of class `cls` (and
    compatibility key `key`), or (None, None)."""
    for n in template_levels(cache, first):
        lv = cache.level(n)
        for a in lv["actors"]:
            if a["class"] == cls and (key is None or compat_key(cls, a.get("props", {})) == key):
                return lv, a["name"]
    return None, None


def actor_meshes(lv, name):
    return [m for m in lv["meshes"] if m["actor"] == name]
