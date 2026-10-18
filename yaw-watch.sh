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
    [[ $line == *YAW_* ]] || continue
    # chat looks like "Name :  text"; ignore what players type
    line=${line%% : *}
    # The console sometimes runs lines together ("YAW_60 YAW_90", "YAW_60 [Timer] ..."),
    # so take the last YAW_<speed> word in the line, not only whole-line matches.
    last=
    rest=$line
    while [[ $rest =~ (^|[^A-Za-z0-9_])(YAW_[0-9]+(\.[0-9]+)?)([^0-9A-Za-z_.]|$) ]]; do
        last=${BASH_REMATCH[2]}
        rest=${rest#*"$last"}
    done
    [ -n "$last" ] && [ -f "$IMG/$last.png" ] && set_img "$IMG/$last.png"
done
