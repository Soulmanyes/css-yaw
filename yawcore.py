"""Everything the app does that is not GUI: settings, yaws.cfg, crosshair images.

The pieces fit together like this:
  - the game runs yaws.cfg (autoexec has `exec yaws.cfg`). Pressing the cycle
    key sets the next cl_yawspeed, plays its sound and echoes YAW_<speed>.
  - `con_logfile yaw.log` copies the console into cstrike/yaw.log.
  - yaw-watch.sh tails that log and copies crosshairs/YAW_<speed>.png over
    ~/.config/css-yaw/current.png. The game runs with KROSSHAIR_IMG pointing at
    that file, and the KROSSHAIR Vulkan layer reloads it inside the game's own
    frames (no compositor overlay, so no stutter).
  - yaw-run is the Steam launch option wrapper: it runs `yawcore.py --apply`,
    sets KROSSHAIR=1 and KROSSHAIR_IMG for the game, and runs yaw-watch.sh for
    as long as the game runs. The app only edits settings.
"""

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import struct
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image

VERSION = "1.0.0"

HOME = Path.home()
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share"))
CONFIG_DIR = XDG_CONFIG / "css-yaw"
SETTINGS = CONFIG_DIR / "settings.json"
CROSSHAIRS = CONFIG_DIR / "crosshairs"
# what the game shows: yaw-run passes it to KROSSHAIR as KROSSHAIR_IMG
CURRENT = CONFIG_DIR / "current.png"
BUILTIN = CONFIG_DIR / "plain-cross.png"
WATCH_ENV = CONFIG_DIR / "watch.env"
# install.sh links yaw-run into ~/.local/bin under this name
RUNNER = "css-yaw-run"
BIN_DIR = HOME / ".local/bin"

CM_DIR = XDG_CONFIG / "crosshair-maker"

# KROSSHAIR, offered as an opt-in download; pinned to the release this was tested with
KROSSHAIR_VERSION = "0.2.5"
KROSSHAIR_URL = ("https://github.com/noahlyk/krosshair/releases/download/"
                 f"v{KROSSHAIR_VERSION}/krosshair-linux-x86_64.tar.gz")
KROSSHAIR_SHA256 = "4f3c8258eb1abb6b6e4b15c55afddbba09296736473206c281e194f094617eef"
KROSSHAIR_LAYER = "VK_LAYER_KROSSHAIR_overlay"
# our own copy lives here; install.sh --uninstall removes both
KROSSHAIR_DIR = XDG_DATA / "css-yaw/krosshair"
KROSSHAIR_JSON = XDG_DATA / "vulkan/implicit_layer.d/css-yaw-krosshair.json"

CS_SUBDIR = Path("steamapps/common/Counter-Strike Source/cstrike")
# Flatpak Steam keeps its libraries here; css-yaw-run can't run inside its sandbox
FLATPAK_STEAM = HOME / ".var/app/com.valvesoftware.Steam"
# first line of every yaws.cfg the app writes; anything else is the user's own file
YAWS_HEADER = "// Written by CS:S Yaw."
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
    # "crosshair-maker", "builtin" or a path to a PNG
    "base": "crosshair-maker",
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
    libraries = _steam_libraries(HOME / ".local/share/Steam") + [HOME / ".steam/steam"]
    for lib in libraries:
        cstrike = lib / CS_SUBDIR
        if (cstrike / "cfg").is_dir():
            return cstrike
    return None


def _steam_libraries(steam):
    libraries = [steam]
    try:
        vdf = (steam / "steamapps/libraryfolders.vdf").read_text()
        libraries += [Path(p) for p in re.findall(r'"path"\s+"([^"]+)"', vdf)]
    except OSError:
        pass
    return libraries


def flatpak_steam_only():
    """True when CS:S is only found in a Flatpak Steam, which isn't supported."""
    if find_cstrike():
        return False
    return any((lib / CS_SUBDIR / "cfg").is_dir()
               for lib in _steam_libraries(FLATPAK_STEAM / ".local/share/Steam"))


def crosshair_maker_png():
    """PNG of the crosshair picked in crosshair-maker, if it is installed."""
    try:
        project = json.loads((CM_DIR / "config.json").read_text())["current_crosshair"]
    except (OSError, ValueError, KeyError):
        return None
    png = Path(project).with_suffix(".png")
    return png if png.is_file() else None


def plain_cross():
    """A simple 22x22 plus, for people without a crosshair of their own."""
    if not BUILTIN.exists():
        BUILTIN.parent.mkdir(parents=True, exist_ok=True)
        im = Image.new("RGBA", (22, 22), (0, 0, 0, 0))
        for i in range(1, 21):
            for j in (10, 11):
                im.putpixel((j, i), (255, 255, 255, 255))
                im.putpixel((i, j), (255, 255, 255, 255))
        im.save(BUILTIN)
    return BUILTIN


def resolve_base(data):
    """The crosshair image the colours are made from. Falls back to the plain cross."""
    base = data.get("base", "crosshair-maker")
    if base == "crosshair-maker":
        png = crosshair_maker_png()
    elif base == "builtin":
        png = None
    else:
        png = Path(base) if Path(base).is_file() else None
    return png or plain_cross()


def layer_dirs():
    """Where the Vulkan loader looks for implicit layers."""
    dirs = [XDG_CONFIG, Path("/etc/xdg"), Path("/etc"), XDG_DATA]
    dirs += [Path(d) for d in os.environ.get("XDG_DATA_DIRS",
                                             "/usr/local/share:/usr/share").split(":") if d]
    return [d / "vulkan/implicit_layer.d" for d in dirs]


def krosshair_installed():
    """Path of an installed KROSSHAIR layer manifest, or None."""
    for folder in layer_dirs():
        for manifest in folder.glob("*.json") if folder.is_dir() else ():
            try:
                if KROSSHAIR_LAYER in manifest.read_text(errors="replace"):
                    return manifest
            except OSError:
                continue
    return None


def krosshair_crosshairs():
    """Folder of the crosshairs that came with the user's KROSSHAIR, if any."""
    for folder in (Path("/usr/share/krosshair/crosshairs"), KROSSHAIR_DIR / "crosshairs"):
        if folder.is_dir():
            return folder
    return None


def can_install_krosshair():
    # upstream only publishes an x86_64 build
    return platform.machine() == "x86_64" and not krosshair_installed()


def install_krosshair(tarball=None):
    """Downloads the pinned KROSSHAIR release into the user's data folder (no root).
    `tarball` is for tests: a local copy of the release archive."""
    if krosshair_installed():
        raise RuntimeError("KROSSHAIR is already installed")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "krosshair.tar.gz"
        if tarball:
            shutil.copyfile(tarball, archive)
        else:
            with urllib.request.urlopen(KROSSHAIR_URL, timeout=30) as r:
                archive.write_bytes(r.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != KROSSHAIR_SHA256:
            raise RuntimeError("The download doesn't match the expected KROSSHAIR release")
        with tarfile.open(archive) as tar:
            wanted = [m for m in tar.getmembers()
                      if m.name.lstrip("./") in ("krosshair.so", "LICENSE", "krosshair.json")
                      or m.name.lstrip("./").startswith("crosshairs/")]
            tar.extractall(tmp, members=wanted, filter="data")
        src = Path(tmp)
        manifest = json.loads((src / "krosshair.json").read_text())
        KROSSHAIR_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / "krosshair.so", KROSSHAIR_DIR / "krosshair.so")
        shutil.copyfile(src / "LICENSE", KROSSHAIR_DIR / "LICENSE")
        if (src / "crosshairs").is_dir():
            shutil.copytree(src / "crosshairs", KROSSHAIR_DIR / "crosshairs", dirs_exist_ok=True)
    manifest["layer"]["library_path"] = str(KROSSHAIR_DIR / "krosshair.so")
    KROSSHAIR_JSON.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(KROSSHAIR_JSON, json.dumps(manifest, indent=4) + "\n")


# ---------------------------------------------------------------- settings

def load_settings():
    try:
        data = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        data = json.loads(json.dumps(DEFAULTS))
    data.setdefault("crosshair", True)
    data.setdefault("base", "crosshair-maker")
    data["start"] = start_index(data)
    for entry in data["entries"]:
        if not entry.get("color"):
            entry["color"] = main_color(resolve_base(data))
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


def write_crosshairs(data, reset_current):
    """One image per yawspeed. reset_current also puts the start yawspeed's image in
    current.png; done at launch (it must exist before the game's first frame), but
    not when applying mid-game, where it would show a different colour than the
    game is on."""
    base = resolve_base(data)
    CROSSHAIRS.mkdir(parents=True, exist_ok=True)
    for old in CROSSHAIRS.glob("*.png"):
        old.unlink()
    for i, entry in enumerate(data["entries"]):
        im = recolor(base, entry["color"])
        im.save(CROSSHAIRS / f"{token(entry['speed'])}.png")
        if i == start_index(data) and (reset_current or not CURRENT.exists()):
            tmp = CURRENT.with_name(CURRENT.name + ".tmp.png")
            im.save(tmp)
            tmp.replace(CURRENT)


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


_BIND = re.compile(r'^\s*bind\s+(?:"([^"]+)"|(\S+))\s+(.*?)\s*$', re.IGNORECASE)


def key_conflicts(cstrike, key):
    """[(file name, command)] for binds of `key` to anything but yaw_cycle in the
    configs that run before yaws.cfg would take the key over."""
    found = []
    for name in ("config.cfg", "autoexec.cfg"):
        try:
            lines = (cstrike / "cfg" / name).read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            m = _BIND.match(line.split("//")[0])
            if not m or (m.group(1) or m.group(2)).lower() != key.lower():
                continue
            command = m.group(3).strip().strip('"')
            if command != "yaw_cycle":
                found.append((name, command))
    return found


def yaws_cfg(data, unbind=()):
    entries = data["entries"]
    lines = [
        f"{YAWS_HEADER} Change it in the app, edits here are overwritten.",
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


# a line that runs yaws.cfg, e.g. `exec yaws`, `exec "yaws.cfg"  // comment`
_EXEC_YAWS = re.compile(r'^\s*exec\s+"?yaws(\.cfg)?"?\s*(//.*)?$', re.IGNORECASE)
_AUTOEXEC_COMMENT = "// added by CS:S Yaw"


def autoexec_runs_yaws(cstrike):
    try:
        lines = (cstrike / "cfg/autoexec.cfg").read_text(errors="replace").splitlines()
    except OSError:
        return False
    return any(_EXEC_YAWS.match(line) for line in lines)


def set_autoexec(cstrike, on):
    """Adds or removes `exec yaws.cfg` in autoexec.cfg. Backs the file up the first time."""
    path = cstrike / "cfg/autoexec.cfg"
    try:
        text = path.read_text(errors="replace")
    except FileNotFoundError:
        text = ""
    backup = path.with_name("autoexec.cfg.bak-css-yaw")
    if text and not backup.exists():
        shutil.copyfile(path, backup)
    lines = text.splitlines()
    if on:
        if any(_EXEC_YAWS.match(line) for line in lines):
            return
        if lines and lines[-1].strip():
            lines.append("")
        lines += [_AUTOEXEC_COMMENT, "exec yaws.cfg"]
    else:
        keep = []
        for line in lines:
            if _EXEC_YAWS.match(line):
                # drop our comment above it too
                if keep and keep[-1].strip() == _AUTOEXEC_COMMENT:
                    keep.pop()
                continue
            keep.append(line)
        while keep and not keep[-1].strip():
            keep.pop()
        lines = keep
    write_text_atomic(path, "\n".join(lines) + "\n")


def write_text_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def apply(data, cstrike, reset_current=False):
    """Write yaws.cfg, crosshair images and watcher env. Returns notes for the user."""
    notes = []
    unbind = [k for k in keys_bound_to_cycle(cstrike) if k != data["key"]]
    for key in unbind:
        notes.append(f"'{key}' gets unbound next time yaws.cfg runs")
    target = cstrike / "cfg/yaws.cfg"
    try:
        theirs = not target.read_text(errors="replace").startswith(YAWS_HEADER)
    except FileNotFoundError:
        theirs = False
    backup = target.with_name("yaws.cfg.bak-css-yaw")
    if theirs and not backup.exists():
        # someone's own yaws.cfg: keep it rather than silently replace it
        shutil.copyfile(target, backup)
        notes.append("Your old yaws.cfg was saved as yaws.cfg.bak-css-yaw")
    write_text_atomic(target, yaws_cfg(data, unbind))
    write_crosshairs(data, reset_current)
    # read by yaw-run (shell), so quote the path: it has spaces
    write_text_atomic(WATCH_ENV, f"LOG={shlex.quote(str(cstrike / 'yaw.log'))}\n"
                                 f"COLORS={1 if data['crosshair'] else 0}\n")
    save_settings(data)
    return notes


def remove_from_game(cstrike):
    """For uninstalling: takes yaws.cfg out of autoexec.cfg and deletes it (if it is
    ours), putting back a yaws.cfg the user had before."""
    set_autoexec(cstrike, False)
    target = cstrike / "cfg/yaws.cfg"
    backup = target.with_name("yaws.cfg.bak-css-yaw")
    try:
        if target.read_text(errors="replace").startswith(YAWS_HEADER):
            target.unlink()
    except FileNotFoundError:
        pass
    if backup.exists() and not target.exists():
        backup.replace(target)


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


def steam_path():
    """PATH Steam runs with: from the running Steam if there is one, otherwise this
    session's (Steam started from the desktop gets the same)."""
    for proc in Path("/proc").iterdir():
        try:
            if proc.name.isdigit() and (proc / "comm").read_text().strip() == "steam":
                env = (proc / "environ").read_bytes().split(b"\0")
                for item in env:
                    if item.startswith(b"PATH="):
                        return item[5:].decode(errors="replace")
        except OSError:
            continue
    return os.environ.get("PATH", "")


def runner():
    """How the launch option should call the wrapper: the short name when Steam can
    find it in ~/.local/bin, otherwise the full path."""
    if str(BIN_DIR) in steam_path().split(":"):
        return RUNNER
    return shlex.quote(str(Path(__file__).resolve().with_name("yaw-run")))


def launch_option(current=None, run=None):
    """The full launch options with the wrapper added, and whether it was there already."""
    run = run or runner()
    current = (current or "").strip()
    if re.search(r"(^|\s)\S*(css-yaw-run|yaw-run)(\s|$)", current):
        # already there; make it the form that works here (short name or full path)
        fixed = re.sub(r"(?<!\S)\S*(css-yaw-run|/yaw-run)(?=\s|$)", lambda _: run, current)
        return fixed, fixed == current
    if "%command%" in current:
        return current.replace("%command%", f"{run} %command%", 1), False
    # options without %command% are passed to the game as arguments
    return " ".join(filter(None, [f"{run} %command%", current])), False


if __name__ == "__main__":
    # `python3 yawcore.py --apply`: rewrite everything from the saved settings (used by yaw-run and install.sh)
    # `python3 yawcore.py --remove-from-game`: undo the game side (used by install.sh --uninstall)
    import sys
    if sys.argv[1:] not in (["--apply"], ["--remove-from-game"]):
        sys.exit("usage: yawcore.py --apply | --remove-from-game")
    cstrike = find_cstrike()
    if not cstrike:
        sys.exit("CS:S not found in your Steam libraries")
    if sys.argv[1] == "--remove-from-game":
        remove_from_game(cstrike)
        sys.exit(0)
    settings = load_settings()
    problems = validate(settings)
    if problems:
        sys.exit("; ".join(problems))
    # runs right before the game starts, so the start yawspeed's colour is correct
    for note in apply(settings, cstrike, reset_current=True):
        print(note)
