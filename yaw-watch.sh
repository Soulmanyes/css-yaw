#!/usr/bin/env bash
# Swaps the KROSSHAIR crosshair when the CS:S yaw_cycle bind echoes "YAW_<speed>".
# KROSSHAIR reloads crosshair-maker's current.png whenever its mtime changes.
# Started by yaw-run with LOG set; on TERM it puts the real crosshair back.
CFG="${XDG_CONFIG_HOME:-$HOME/.config}/css-yaw"
IMG="$CFG/crosshairs"
CUR="${XDG_CONFIG_HOME:-$HOME/.config}/crosshair-maker/projects/current.png"
: "${LOG:?LOG not set; open CS:S Yaw and press Apply}"

set_img() {
    # copy then rename, so the layer never reads a half-written PNG
    cp "$1" "$CUR.tmp" && mv -f "$CUR.tmp" "$CUR"
}

stop() {
    kill "$TAIL" 2>/dev/null
    # put the real crosshair back so a leftover colour never shows next launch
    [ -f "$IMG/original.png" ] && ! cmp -s "$IMG/original.png" "$CUR" && set_img "$IMG/original.png"
    exit 0
}
trap stop TERM INT HUP

# con_logfile appends forever; start fresh each launch
: > "$LOG"
# skip the reload if that crosshair is already in place
[ -f "$IMG/default.png" ] && ! cmp -s "$IMG/default.png" "$CUR" && set_img "$IMG/default.png"

exec {LOGFD}< <(tail -n0 -F "$LOG" 2>/dev/null)
TAIL=$!
while IFS= read -r line <&"$LOGFD"; do
    # echo leaves a trailing space (and maybe \r); strip all whitespace
    line=${line//[[:space:]]/}
    # whole-line match so chat containing "YAW_210" does not trigger it
    [[ $line =~ ^YAW_[0-9.]+$ ]] || continue
    [ -f "$IMG/$line.png" ] && set_img "$IMG/$line.png"
done
