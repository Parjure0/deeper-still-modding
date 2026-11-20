"""Finding the installed game and running its command-line tools.

Pure Python (no bpy): also usable from a terminal or a test.

The game is found in this order:
1. the folder set in the add-on preferences ("Game folder");
2. the Steam libraries: Steam's own folder (Windows registry, usual paths),
   then every library listed in `steamapps/libraryfolders.vdf`; in each
   library, `steamapps/appmanifest_<APP_ID>.acf` gives the install folder
   (`steamapps/common/<installdir>`); without a manifest, every folder of
   `steamapps/common` that contains the game executable.

Game commands used by the kit (options of the shipped game):
- `--extraire-assets <folder>`  extract the game's meshes, textures and data
  (shipped names, no engine names) into a local cache;
- `--mod <folder> --level <map>`  play a level of a mod folder;
- `--mod-verifier <folder>`  check a mod folder (one error per line);
- `--workshop-envoyer <folder>`  publish a mod folder to the Steam Workshop.
"""

import json
import os
import re
import subprocess
import sys

APP_ID = "2484890"          # Deeper Still (full game; the demo has no Workshop)
EXE_NAMES = ("DeeperStill.exe", "DeeperStill")
KIT_FOLDER = "DeeperStillModKit"
STAMP = "modkit_stamp.json"  # written in the cache after an extraction


# --- VDF (Valve KeyValues text) ---------------------------------------------------

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text):
    """Nested dicts from a Valve KeyValues text file (libraryfolders.vdf,
    appmanifest_*.acf). Keys are kept as written; duplicate keys: last wins."""
    stack = [{}]
    key = None
    for m in _TOKEN.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            d = {}
            if key is not None:
                stack[-1][key] = d
            stack.append(d)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = s.replace("\\\\", "\\")
        else:
            stack[-1][key] = s.replace("\\\\", "\\")
            key = None
    return stack[0]


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


# --- Steam ------------------------------------------------------------------------

def _registry_steam_paths():
    if sys.platform != "win32":
        return []
    out = []
    try:
        import winreg
    except ImportError:
        return out
    for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                v, _ = winreg.QueryValueEx(k, value)
                if v:
                    out.append(os.path.normpath(v))
        except OSError:
            pass
    return out


def default_steam_roots():
    """Usual Steam folders of this computer (existing ones only)."""
    cands = _registry_steam_paths()
    if sys.platform == "win32":
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(env)
            if base:
                cands.append(os.path.join(base, "Steam"))
    elif sys.platform == "darwin":
        cands.append(os.path.expanduser("~/Library/Application Support/Steam"))
    else:
        cands += [os.path.expanduser("~/.steam/steam"), os.path.expanduser("~/.local/share/Steam"),
                  os.path.expanduser("~/.var/app/com.valvesoftware.Steam/data/Steam")]
    out = []
    for c in cands:
        n = os.path.normcase(os.path.normpath(c))
        if os.path.isdir(c) and n not in {os.path.normcase(os.path.normpath(o)) for o in out}:
            out.append(c)
    return out


def steam_libraries(steam_roots):
    """Steam library folders: each root, then those of its libraryfolders.vdf."""
    libs = []

    def add(p):
        p = os.path.normpath(p)
        if os.path.isdir(p) and os.path.normcase(p) not in {os.path.normcase(x) for x in libs}:
            libs.append(p)

    for root in steam_roots:
        add(root)
        for vdf in (os.path.join(root, "steamapps", "libraryfolders.vdf"),
                    os.path.join(root, "config", "libraryfolders.vdf")):
            text = _read(vdf)
            if text is None:
                continue
            data = parse_vdf(text)
            folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
            for k, v in folders.items():
                if isinstance(v, dict) and v.get("path"):
                    add(v["path"])
                elif isinstance(v, str) and k.isdigit():  # old format: "1" "<library folder>"
                    add(v)
    return libs


def find_exe(folder):
    """Game executable in `folder`, or None."""
    for n in EXE_NAMES:
        p = os.path.join(folder, n)
        if os.path.isfile(p):
            return p
    return None


def find_game(steam_roots=None, override=None):
    """(executable, how it was found) of the installed game, or (None, reason)."""
    if override:
        exe = override if os.path.isfile(override) else find_exe(override)
        if exe:
            return os.path.normpath(exe), "game folder set in the preferences"
        return None, f"no {EXE_NAMES[0]} in the game folder set in the preferences: {override}"
    roots = default_steam_roots() if steam_roots is None else list(steam_roots)
    if not roots:
        return None, "Steam not found (set the game folder in the add-on preferences)"
    libs = steam_libraries(roots)
    # 1. App manifest: exact install folder.
    for lib in libs:
        acf = _read(os.path.join(lib, "steamapps", f"appmanifest_{APP_ID}.acf"))
        if acf is None:
            continue
        state = parse_vdf(acf).get("AppState", {})
        installdir = state.get("installdir")
        if installdir:
            exe = find_exe(os.path.join(lib, "steamapps", "common", installdir))
            if exe:
                return os.path.normpath(exe), f"Steam library {lib}"
    # 2. Any folder of steamapps/common holding the executable.
    for lib in libs:
        common = os.path.join(lib, "steamapps", "common")
        try:
            names = sorted(os.listdir(common))
        except OSError:
            continue
        for n in names:
            exe = find_exe(os.path.join(common, n))
            if exe:
                return os.path.normpath(exe), f"Steam library {lib}"
    return None, f"Deeper Still not found in the Steam libraries ({', '.join(libs) or 'none'})"


# --- Local folders ----------------------------------------------------------------

def user_data_dir():
    """Per-user folder of the kit (cache of extracted game files, play-test
    files); environment variable DSMK_USER_DIR to use another one."""
    if os.environ.get("DSMK_USER_DIR"):
        return os.environ["DSMK_USER_DIR"]
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, KIT_FOLDER)


def default_cache_dir():
    return os.path.join(user_data_dir(), "extracted")


def exe_signature(exe):
    st = os.stat(exe)
    return {"exe": os.path.normcase(os.path.abspath(exe)), "size": st.st_size, "mtime": int(st.st_mtime)}


def cache_state(cache_dir, exe=None):
    """'missing', 'outdated' (the game changed since the extraction) or 'ok'."""
    try:
        with open(os.path.join(cache_dir, STAMP), encoding="utf-8") as f:
            stamp = json.load(f)
    except (OSError, ValueError):
        return "missing"
    if exe and os.path.isfile(exe):
        sig = exe_signature(exe)
        if stamp.get("size") != sig["size"] or stamp.get("mtime") != sig["mtime"]:
            return "outdated"
    return "ok"


def write_stamp(cache_dir, exe):
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, STAMP), "w", encoding="utf-8") as f:
        json.dump(exe_signature(exe), f, indent=1)


# --- Running the game -------------------------------------------------------------

def _flags(background):
    if sys.platform == "win32" and background:
        return subprocess.CREATE_NO_WINDOW
    return 0


def run_tool(exe, args, timeout=600):
    """Run the game as a command-line tool (no window); returns (exit code, output lines)."""
    proc = subprocess.run([exe, *args], cwd=os.path.dirname(exe), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, creationflags=_flags(True))
    lines = (proc.stdout or "").splitlines() + (proc.stderr or "").splitlines()
    return proc.returncode, [l for l in lines if l.strip()]


def extract_assets(exe, cache_dir, timeout=1800):
    code, lines = run_tool(exe, ["--extraire-assets", cache_dir], timeout)
    if code == 0:
        write_stamp(cache_dir, exe)
    return code, lines


def verify_mod(exe, mod_dir, timeout=600):
    return run_tool(exe, ["--mod-verifier", mod_dir], timeout)


def bake_args(mod_dir, map_name):
    return ["--headless", "--mod", mod_dir, "--bake-navmesh", "--levels", map_name]


def bake_navmesh(exe, mod_dir, map_name, timeout=1800):
    """Navigation of the level computed by the game (no window) and written in
    the mod (`navmesh/<level>.nav`): NPCs move as soon as the level starts.
    Without it (or out of date), the game computes it when the level loads."""
    return run_tool(exe, bake_args(mod_dir, map_name), timeout)


def publish_mod(exe, mod_dir, timeout=3600):
    """Publish to the Steam Workshop (the game asks Steam; the item stays private
    until its owner changes it on Steam)."""
    return run_tool(exe, ["--workshop-envoyer", mod_dir], timeout)


def play_args(mod_dirs, map_name, extra=()):
    args = []
    for d in mod_dirs:
        args += ["--mod", d]
    return args + ["--level", map_name, *extra]


def play(exe, mod_dirs, map_name, extra=(), log_path=None):
    """Start the game on a mod level (window); returns the process."""
    log = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL
    try:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        return subprocess.Popen([exe, *play_args(mod_dirs, map_name, extra)], cwd=os.path.dirname(exe),
                                stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    finally:
        if log_path:
            log.close()
