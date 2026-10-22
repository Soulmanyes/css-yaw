#!/usr/bin/env python3
"""Source Yaw input service: forwards a fixed set of key and mouse events.

Runs as root under systemd, started by sourceyaw-inputd.socket when the strafe
trainer connects, and exits a while after the last client leaves. It reads
every keyboard and mouse under /dev/input but passes on only the keys and
mouse axes listed in /etc/sourceyaw-inputd.conf, so a client never sees
anything else typed on the keyboard. The list lives in a root-owned file on
purpose: a client cannot ask for more keys.

Each forwarded event is 20 bytes, little endian: seconds (int64),
microseconds (uint32), type (uint16), code (uint16), value (int32). The time is
the kernel's own event time, so socket delays do not skew the trainer's
tick maths.
"""

import os
import select
import socket
import struct
import sys
import time

CONFIG = "/etc/sourceyaw-inputd.conf"
IDLE_EXIT = 30  # seconds without clients before the service stops
RESCAN = 2  # seconds between looks for plugged in devices

EV_KEY, EV_REL = 0x01, 0x02
INPUT_EVENT = struct.Struct("@llHHi")  # struct input_event on 64-bit Linux
OUT_EVENT = struct.Struct("<qIHHi")

KEYS = {f"KEY_{c}": code for c, code in zip(
    "QWERTYUIOP", range(16, 26))}
KEYS.update({f"KEY_{c}": code for c, code in zip("ASDFGHJKL", range(30, 39))})
KEYS.update({f"KEY_{c}": code for c, code in zip("ZXCVBNM", range(44, 51))})
KEYS.update({f"KEY_{d}": code for d, code in zip("1234567890", range(2, 12))})
KEYS.update({
    "KEY_SPACE": 57, "KEY_LEFTALT": 56, "KEY_RIGHTALT": 100, "KEY_LEFTCTRL": 29,
    "KEY_RIGHTCTRL": 97, "KEY_LEFTSHIFT": 42, "KEY_RIGHTSHIFT": 54, "KEY_TAB": 15,
    "KEY_CAPSLOCK": 58, "KEY_BACKSPACE": 14, "KEY_UP": 103, "KEY_DOWN": 108,
    "KEY_LEFT": 105, "KEY_RIGHT": 106,
    "BTN_LEFT": 272, "BTN_RIGHT": 273, "BTN_MIDDLE": 274, "BTN_SIDE": 275, "BTN_EXTRA": 276,
})
RELS = {"REL_X": 0, "REL_Y": 1, "REL_WHEEL": 8, "REL_WHEEL_HI_RES": 11}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def read_config():
    user, keys, rels = None, set(), set()
    with open(CONFIG) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line or "=" not in line:
                continue
            name, value = (p.strip() for p in line.split("=", 1))
            if name == "user":
                user = value
            elif name == "keys":
                for k in value.split():
                    if k in KEYS:
                        keys.add(KEYS[k])
                    else:
                        log(f"unknown key in config: {k}")
            elif name == "axes":
                for r in value.split():
                    if r in RELS:
                        rels.add(RELS[r])
                    else:
                        log(f"unknown axis in config: {r}")
    if user is None:
        raise SystemExit("config has no user = line")
    import pwd
    return pwd.getpwnam(user).pw_uid, keys, rels


def input_devices():
    """event nodes of keyboards and mice, from /proc/bus/input/devices."""
    found = []
    with open("/proc/bus/input/devices") as f:
        blocks = f.read().split("\n\n")
    for block in blocks:
        handlers, bits = [], {}
        for line in block.splitlines():
            if line.startswith("H: Handlers="):
                handlers = line.split("=", 1)[1].split()
            elif line.startswith("B: "):
                name, value = line[3:].split("=", 1)
                bits[name] = int("".join(f"{int(w, 16):016x}" for w in value.split()), 16)
        events = [h for h in handlers if h.startswith("event")]
        if not events:
            continue
        key, rel = bits.get("KEY", 0), bits.get("REL", 0)
        keyboard = key >> KEYS["KEY_A"] & 1
        mouse = rel & 1 and key >> KEYS["BTN_LEFT"] & 1
        if keyboard or mouse:
            found.append("/dev/input/" + events[0])
    return found


def main():
    uid, keys, rels = read_config()

    fds = int(os.environ.get("LISTEN_FDS", "0"))
    if fds < 1 or os.environ.get("LISTEN_PID") != str(os.getpid()):
        raise SystemExit("start this through sourceyaw-inputd.socket")
    listener = socket.socket(fileno=3)
    listener.setblocking(False)

    devices = {}  # fd -> path
    clients = set()
    last_client = time.monotonic()
    next_scan = 0.0

    while True:
        now = time.monotonic()
        if now >= next_scan:
            next_scan = now + RESCAN
            open_paths = set(devices.values())
            for path in input_devices():
                if path in open_paths:
                    continue
                try:
                    devices[os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)] = path
                except OSError as e:
                    log(f"cannot open {path}: {e}")

        if clients:
            last_client = now
        elif now - last_client > IDLE_EXIT:
            return 0

        ready, _, _ = select.select([listener, *devices, *clients], [], [], 1.0)
        out = bytearray()
        for r in ready:
            if r is listener:
                try:
                    conn, _ = listener.accept()
                except BlockingIOError:
                    continue
                creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                _, peer_uid, _ = struct.unpack("3i", creds)
                if peer_uid not in (uid, 0):
                    log(f"refused client with uid {peer_uid}")
                    conn.close()
                    continue
                conn.setblocking(False)
                clients.add(conn)
            elif r in clients:
                # clients never send anything; readable means closed
                try:
                    if not r.recv(64):
                        raise OSError
                except BlockingIOError:
                    pass
                except OSError:
                    clients.discard(r)
                    r.close()
            else:
                try:
                    data = os.read(r, INPUT_EVENT.size * 64)
                except BlockingIOError:
                    continue
                except OSError:  # unplugged
                    os.close(r)
                    devices.pop(r, None)
                    continue
                for sec, usec, etype, code, value in INPUT_EVENT.iter_unpack(data):
                    if etype == EV_KEY and code in keys and value != 2:  # 2 = autorepeat
                        out += OUT_EVENT.pack(sec, usec, etype, code, value)
                    elif etype == EV_REL and code in rels:
                        out += OUT_EVENT.pack(sec, usec, etype, code, value)
        if out:
            for c in list(clients):
                try:
                    c.sendall(out)
                except (BlockingIOError, OSError):
                    # a client that cannot keep up is dropped rather than
                    # letting events pile up in root's memory
                    clients.discard(c)
                    c.close()


if __name__ == "__main__":
    sys.exit(main())
