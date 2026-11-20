"""Shared state of the add-on: preferences, installed game, extracted cache, report."""

import os
import threading

import bpy

from . import game, gamedata

_cache = {"path": None, "obj": None}
_game = {"key": None, "exe": None, "how": ""}

# Report shown in the panel (written by worker threads, read by the UI).
STATUS = {"state": "", "lines": [], "busy": False}
_lock = threading.Lock()


def prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


def cache_dir():
    """Folder of the extracted game files (preferences, else environment
    variable DSMK_CACHE_DIR, else the kit's user folder)."""
    p = prefs()
    if (p is None or not p.cache_dir) and os.environ.get("DSMK_CACHE_DIR"):
        return os.environ["DSMK_CACHE_DIR"]
    d = p.cache_dir if p is not None and p.cache_dir else game.default_cache_dir()
    return bpy.path.abspath(d)


def cache():
    """gamedata.Cache of the extracted game files (None if not extracted)."""
    d = cache_dir()
    if _cache["path"] != d or _cache["obj"] is None:
        c = gamedata.Cache(d)
        _cache["path"], _cache["obj"] = d, (c if c.ok() else None)
    return _cache["obj"]


def forget_cache():
    _cache["path"] = _cache["obj"] = None


def game_exe(refresh=False):
    """(executable, how it was found / why not)."""
    p = prefs()
    override = bpy.path.abspath(p.game_folder) if p is not None and p.game_folder else None
    override = override or os.environ.get("DSMK_GAME_FOLDER") or None
    if refresh or _game["key"] != override or _game["exe"] is None:
        exe, how = game.find_game(override=override)
        _game.update(key=override, exe=exe, how=how)
    return _game["exe"], _game["how"]


def level_names():
    c = cache()
    return c.level_names() if c is not None else []


def status(state=None, line=None, busy=None, clear=False):
    with _lock:
        if clear:
            STATUS["lines"] = []
        if state is not None:
            STATUS["state"] = state
        if line is not None:
            STATUS["lines"].append(line)
        if busy is not None:
            STATUS["busy"] = busy


def status_copy():
    with _lock:
        return STATUS["state"], list(STATUS["lines"]), STATUS["busy"]


def redraw():
    if bpy.app.background:
        return
    try:
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == "VIEW_3D":
                    a.tag_redraw()
    except (AttributeError, ReferenceError):
        pass


def _timer():
    redraw()
    return 0.25 if STATUS["busy"] else None


def run_in_thread(fn):
    """Run `fn()` in a worker thread (synchronously in background mode); the
    panel is redrawn while it works."""
    if bpy.app.background:
        fn()
        return
    threading.Thread(target=fn, daemon=True).start()
    if not bpy.app.timers.is_registered(_timer):
        bpy.app.timers.register(_timer, first_interval=0.25)


def unregister():
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)


def mod_dir(scene):
    d = scene.dsmk.mod_dir
    return os.path.normpath(bpy.path.abspath(d)) if d else ""
