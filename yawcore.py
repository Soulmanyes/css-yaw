"""Everything the app does that is not GUI: settings, yaws.cfg, crosshair images.

The pieces fit together like this:
  - the game runs yaws.cfg (autoexec has `exec yaws.cfg`). Pressing the cycle
    key sets the next cl_yawspeed, plays its sound and echoes YAW_<speed>.
  - `con_logfile yaw.log` copies the console into cstrike/yaw.log.
  - yaw-watch.sh tails that log and copies crosshairs/YAW_<speed>.png over
    crosshair-maker's current.png, which the KROSSHAIR Vulkan layer reloads
    inside the game's own frames (no compositor overlay, so no stutter).
  - yaw-run is the Steam launch option wrapper: it runs `yawcore.py --apply`,
    starts yaw-watch.sh for as long as the game runs, then restores the crosshair.
    The app only edits settings (and applies them right away for convenience).
"""

import json
import os
import re
import shlex
import shutil
import struct
import subprocess
from pathlib import Path

from PIL import Image

HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "css-yaw"
SETTINGS = CONFIG_DIR / "settings.json"
CROSSHAIRS = CONFIG_DIR / "crosshairs"
WATCH_ENV = CONFIG_DIR / "watch.env"
# install.sh links yaw-run here; Steam has ~/.local/bin in its PATH
RUNNER = "css-yaw-run"

CM_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "crosshair-maker"
CM_PROJECTS = CM_DIR / "projects"
# KROSSHAIR prefers these over current.png; if one exists, swapping current.png does nothing
CM_SHADOWING = ("current.apng", "current.gif")

CS_SUBDIR = Path("steamapps/common/Counter-Strike Source/cstrike")
CSS_APPID = "240"

# short UI sounds to offer; the app only lists the ones this game install has
SOUNDS = ["buttons/blip1", "buttons/blip2", "buttons/button10", "buttons/button11",
          "buttons/button14", "buttons/button15", "buttons/button16", "buttons/button17",
          "buttons/button18", "buttons/button19"]

# key names the Source engine accepts in `bind`
VALID_KEYS = set(
    [chr(c) for c in range(ord("a"), ord("z") + 1)]
    + [str(d) for d in range(10)]
    + [f"f{n}" for n in range(1, 13)]
    + [f"mouse{n}" for n in range(1, 6)]
    + ["mwheelup", "mwheeldown", "space", "tab", "enter", "escape", "backspace",
       "capslock", "shift", "rshift", "ctrl", "rctrl", "alt", "ralt", "lwin",
       "rwin", "app", "ins", "del", "home", "end", "pgup", "pgdn", "uparrow",
       "downarrow", "leftarrow", "rightarrow", "pause", "scrolllock", "numlock",
       "kp_ins", "kp_end", "kp_downarrow", "kp_pgdn", "kp_leftarrow", "kp_5",
       "kp_rightarrow", "kp_home", "kp_uparrow", "kp_pgup", "kp_enter", "kp_del",
       "kp_slash", "kp_multiply", "kp_minus", "kp_plus", "semicolon", "'", "`",
       "-", "=", "[", "]", "\\", ",", ".", "/"]
)

DEFAULTS = {
    "key": "q",
    "crosshair": True,
    # index into entries of the yawspeed the game starts on
    "start": 0,
    "entries": [
        {"speed": 90, "color": None, "sound": "buttons/blip1"},
        {"speed": 210, "color": "#ff00ff", "sound": "buttons/button17"},
    ],
}


def fmt_speed(value):
    """210.0 -> '210', 293.95350 -> '293.9535'. Used for both the cvar and the token."""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def token(value):
    return f"YAW_{fmt_speed(value)}"


# ---------------------------------------------------------------- locations

def find_cstrike():
    """cstrike folder of the first Steam library that has CS:S installed."""
    libraries = [HOME / ".local/share/Steam", HOME / ".steam/steam"]
    vdf = HOME / ".local/share/Steam/steamapps/libraryfolders.vdf"
    try:
        libraries += [Path(p) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text())]
    except OSError:
        pass
    for lib in libraries:
        cstrike = lib / CS_SUBDIR
        if (cstrike / "cfg").is_dir():
            return cstrike
    return None


def base_crosshair():
    """PNG of the crosshair picked in crosshair-maker (never current.png, which we overwrite)."""
    try:
        project = json.loads((CM_DIR / "config.json").read_text())["current_crosshair"]
    except (OSError, ValueError, KeyError):
        return None
    png = Path(project).with_suffix(".png")
    return png if png.is_file() else None


def shadowing_files():
    return [name for name in CM_SHADOWING if (CM_PROJECTS / name).exists()]


def krosshair_installed():
    return Path("/usr/share/vulkan/implicit_layer.d/krosshair.json").exists()


# ---------------------------------------------------------------- settings

def load_settings(base=None):
    try:
        data = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        data = json.loads(json.dumps(DEFAULTS))
    data.setdefault("crosshair", True)
    data["start"] = start_index(data)
    for entry in data["entries"]:
        if not entry.get("color"):
            entry["color"] = main_color(base) if base else "#00ff37"
    return data


def save_settings(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(SETTINGS)


def start_index(data):
    start = data.get("start", 0)
    return start if isinstance(start, int) and 0 <= start < len(data["entries"]) else 0


def validate(data):
    """List of problems that block Apply; empty when fine."""
    problems = []
    if data["key"] not in VALID_KEYS:
        problems.append(f"'{data['key']}' is not a key name CS:S knows")
    if not data["entries"]:
        problems.append("Add at least one yawspeed")
    tokens = [token(e["speed"]) for e in data["entries"]]
    if len(set(tokens)) != len(tokens):
        problems.append("Each yawspeed must be different")
    return problems


# ---------------------------------------------------------------- crosshair images

def main_color(png):
    """Most common visible colour of a crosshair, as #rrggbb."""
    im = Image.open(png).convert("RGBA")
    counts = {}
    for r, g, b, a in im.get_flattened_data():
        if a:
            counts[(r, g, b)] = counts.get((r, g, b), 0) + 1
    if not counts:
        return "#ffffff"
    return "#%02x%02x%02x" % max(counts, key=counts.get)


def recolor(png, color):
    """Every visible pixel becomes `color`, alpha kept. Outlines lose their own colour."""
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    im = Image.open(png).convert("RGBA")
    im.putdata([(*rgb, a) if a else (r, g, b, a) for r, g, b, a in im.get_flattened_data()])
    return im


def write_crosshairs(data, base):
    CROSSHAIRS.mkdir(parents=True, exist_ok=True)
    for old in CROSSHAIRS.glob("YAW_*.png"):
        old.unlink()
    for i, entry in enumerate(data["entries"]):
        im = recolor(base, entry["color"])
        im.save(CROSSHAIRS / f"{token(entry['speed'])}.png")
        if i == start_index(data):
            # shown when the watcher starts, before the game has echoed anything
            im.save(CROSSHAIRS / "default.png")
    # put back when the watcher stops
    shutil.copyfile(base, CROSSHAIRS / "original.png")


# ---------------------------------------------------------------- game config

def keys_bound_to_cycle(cstrike):
    """Keys config.cfg binds to yaw_cycle. It keeps binds across launches and the
    game rewrites it on exit, so a key that was changed away from stays bound
    there until yaws.cfg unbinds it."""
    try:
        text = (cstrike / "cfg/config.cfg").read_text(errors="replace")
    except OSError:
        return []
    return re.findall(r'^bind "([^"]+)" "yaw_cycle"', text, re.MULTILINE)


def yaws_cfg(data, unbind=()):
    entries = data["entries"]
    lines = [
        "// Written by CS:S Yaw. Change it in the app, edits here are overwritten.",
        "// echo goes to the console and yaw.log (read by the crosshair watcher);",
        "// play is a local-only sound cue.",
        "con_logfile yaw.log",
        "",
    ]
    for i, entry in enumerate(entries):
        speed = fmt_speed(entry["speed"])
        nxt = (i + 1) % len(entries) + 1
        parts = [f"cl_yawspeed {speed}", f"echo {token(speed)}"]
        if entry.get("sound"):
            parts.append(f"play {entry['sound']}")
        parts.append(f"alias yaw_cycle yaw_set{nxt}")
        lines.append(f'alias yaw_set{i + 1} "{"; ".join(parts)}"')
    start = start_index(data)
    first = fmt_speed(entries[start]["speed"])
    lines += [
        "",
        "// start on the chosen yawspeed (no sound at launch); the next press goes to the one after it",
        f"cl_yawspeed {first}",
        f"echo {token(first)}",
        f'alias yaw_cycle "yaw_set{(start + 1) % len(entries) + 1}"',
        "",
    ]
    for key in unbind:
        lines.append(f'unbind "{key}"')
    lines.append(f'bind "{data["key"]}" "yaw_cycle"')
    return "\n".join(lines) + "\n"


def write_text_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def apply(data, cstrike, base):
    """Write yaws.cfg, crosshair images and watcher env. Returns notes for the user."""
    notes = []
    unbind = [k for k in keys_bound_to_cycle(cstrike) if k != data["key"]]
    for key in unbind:
        notes.append(f"'{key}' gets unbound next time yaws.cfg runs")
    write_text_atomic(cstrike / "cfg/yaws.cfg", yaws_cfg(data, unbind))
    write_crosshairs(data, base)
    # read by yaw-run (shell), so quote the path: it has spaces
    write_text_atomic(WATCH_ENV, f"LOG={shlex.quote(str(cstrike / 'yaw.log'))}\n"
                                 f"COLORS={1 if data['crosshair'] else 0}\n")
    save_settings(data)
    return notes


# ---------------------------------------------------------------- sound preview

SOUND_CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "css-yaw/sounds"
# where the game looks for sounds, in the order it looks
SOUND_VPKS = ("cstrike/cstrike_pak_dir.vpk", "hl2/hl2_sound_misc_dir.vpk",
              "hl2/hl2_misc_dir.vpk")
_vpk_trees = {}


def _vpk_tree(dir_vpk):
    """{path: (archive_index, offset, length, preload_bytes, data_start)} of a _dir.vpk."""
    if dir_vpk in _vpk_trees:
        return _vpk_trees[dir_vpk]
    tree = {}
    with open(dir_vpk, "rb") as f:
        sig, version, tree_size = struct.unpack("<III", f.read(12))
        if sig != 0x55AA1234:
            raise ValueError(f"{dir_vpk} is not a VPK")
        header = 12 if version == 1 else 28
        f.seek(header)
        blob = f.read(tree_size)
    pos = 0

    def string():
        nonlocal pos
        end = blob.index(b"\0", pos)
        text = blob[pos:end].decode("utf-8", "replace")
        pos = end + 1
        return text

    while (ext := string()):
        while (folder := string()):
            while (name := string()):
                _crc, preload, archive, offset, length, _end = struct.unpack_from(
                    "<IHHIIH", blob, pos)
                pos += 18
                tree[f"{folder}/{name}.{ext}".lower()] = (archive, offset, length,
                                                          blob[pos:pos + preload])
                pos += preload
    _vpk_trees[dir_vpk] = (tree, header + tree_size)
    return _vpk_trees[dir_vpk]


def _read_from_vpk(dir_vpk, path):
    tree, data_start = _vpk_tree(dir_vpk)
    hit = tree.get(path.lower())
    if not hit:
        return None
    archive, offset, length, preload = hit
    if archive == 0x7FFF:  # stored in the _dir.vpk itself, after the tree
        source, offset = dir_vpk, data_start + offset
    else:
        source = str(dir_vpk).replace("_dir.vpk", f"_{archive:03d}.vpk")
    with open(source, "rb") as f:
        f.seek(offset)
        return preload + f.read(length)


def sound_file(cstrike, sound):
    """Local file for a `play` sound name like buttons/blip1, extracting it if needed."""
    game = cstrike.parent
    for ext in (".wav", ".mp3"):
        rel = f"sound/{sound}{ext}"
        loose = cstrike / rel
        if loose.is_file():
            return loose
        cached = SOUND_CACHE / f"{sound}{ext}"
        if cached.is_file():
            return cached
        for vpk in SOUND_VPKS:
            try:
                data = _read_from_vpk(game / vpk, rel)
            except (OSError, ValueError):
                continue
            if data:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(data)
                return cached
    return None


def available_sounds(cstrike):
    return [s for s in SOUNDS if sound_file(cstrike, s)]


def play_sound(cstrike, sound):
    """Plays a game sound on the desktop. False if the game doesn't have it."""
    path = sound_file(cstrike, sound)
    if not path:
        return False
    for player in (["pw-play"], ["paplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
        if shutil.which(player[0]):
            subprocess.Popen([*player, str(path)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
    return False


# ---------------------------------------------------------------- launch option

def _parse_vdf(text):
    """Steam's text KeyValues format -> nested dicts (keys lower-cased)."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    pos = 0

    def block():
        nonlocal pos
        out = {}
        while pos < len(tokens):
            text, brace = tokens[pos]
            pos += 1
            if brace == "}":
                return out
            if brace == "{":
                continue  # stray brace; skip
            key = text.lower()
            nxt_text, nxt_brace = tokens[pos] if pos < len(tokens) else ("", "")
            pos += 1
            if nxt_brace == "{":
                out[key] = block()
            else:
                out[key] = nxt_text.replace('\\"', '"').replace("\\\\", "\\")
        return out

    return block()


def current_launch_options():
    """CS:S launch options of the most recently used Steam account, or None if unknown."""
    files = sorted((HOME / ".local/share/Steam/userdata").glob("*/config/localconfig.vdf"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for vdf in files:
        try:
            tree = _parse_vdf(vdf.read_text(errors="replace"))
        except OSError:
            continue
        node = tree.get("userlocalconfigstore", {})
        for key in ("software", "valve", "steam", "apps", CSS_APPID):
            node = node.get(key, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict):
            return node.get("launchoptions", "")
    return None


def launch_option(current=None):
    """The full launch options with the wrapper added, and whether it was there already."""
    current = (current or "").strip()
    if re.search(r"(^|\s)\S*(css-yaw-run|yaw-run)(\s|$)", current):
        # already there; also swap an old full path for the short command
        fixed = re.sub(r"\S*/yaw-run(?=\s|$)", RUNNER, current)
        return fixed, fixed == current
    if "%command%" in current:
        return current.replace("%command%", f"{RUNNER} %command%", 1), False
    # options without %command% are passed to the game as arguments
    return " ".join(filter(None, [f"{RUNNER} %command%", current])), False


if __name__ == "__main__":
    # `python3 yawcore.py --apply`: rewrite everything from the saved settings (used by yaw-run and install.sh)
    import sys
    if sys.argv[1:] != ["--apply"]:
        sys.exit("usage: yawcore.py --apply")
    cstrike, base = find_cstrike(), base_crosshair()
    if not cstrike or not base:
        sys.exit("CS:S or the crosshair-maker crosshair not found; open the app instead")
    settings = load_settings(base)
    problems = validate(settings)
    if problems:
        sys.exit("; ".join(problems))
    for note in apply(settings, cstrike, base):
        print(note)
