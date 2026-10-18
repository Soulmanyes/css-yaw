#!/usr/bin/env bash
# Swaps the crosshair when the CS:S yaw_cycle bind echoes "YAW_<speed>".
# yaw-run starts the game with KROSSHAIR_IMG pointing at current.png, and
# KROSSHAIR reloads that file whenever its mtime changes.
CFG="${XDG_CONFIG_HOME:-$HOME/.config}/sourceyaw"
IMG="$CFG/crosshairs"
CUR="$CFG/current.png"
: "${LOG:?LOG not set; open Source Yaw and press Apply}"

set_img() {
    # copy then rename, so the layer never reads a half-written PNG
    cp "$1" "$CUR.tmp" && mv -f "$CUR.tmp" "$CUR"
}

trap 'kill "$TAIL" 2>/dev/null; exit 0' TERM INT HUP

# con_logfile appends forever; start fresh each launch
: > "$LOG"

exec {LOGFD}< <(tail -n0 -F "$LOG" 2>/dev/null)
TAIL=$!
while IFS= read -r line <&"$LOGFD"; do
    # echo leaves a trailing space (and maybe \r); strip all whitespace
    line=${line//[[:space:]]/}
    # whole-line match so chat containing "YAW_210" does not trigger it
    [[ $line =~ ^YAW_[0-9.]+$ ]] || continue
    [ -f "$IMG/$line.png" ] && set_img "$IMG/$line.png"
done
