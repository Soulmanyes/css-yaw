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
# Finds the last YAW_<speed> in some console text and shows that colour. With
# complete=0 the text may be cut off mid-line, so a token only counts once something
# follows it (echo writes "YAW_210 " with a trailing space). Returns 0 if the text
# is done with, 1 if it should be kept for more input.
handle() {
    local text=$1 complete=$2 last= rest end
    # chat looks like "Name :  text"; ignore what players type
    text=${text%% : *}
    rest=$text
    if [ "$complete" = 1 ]; then end='([^0-9A-Za-z_.]|$)'; else end='([^0-9A-Za-z_.])'; fi
    while [[ $rest =~ (^|[^A-Za-z0-9_])(YAW_[0-9]+(\.[0-9]+)?)$end ]]; do
        last=${BASH_REMATCH[2]}
        rest=${rest#*"$last"}
    done
    if [ -n "$last" ]; then
        [ -f "$IMG/$last.png" ] && set_img "$IMG/$last.png"
        return 0
    fi
    # nothing yet: keep a possibly unfinished token, drop anything else
    [ "$complete" = 1 ] || [[ $text != *YAW_* ]]
}

# The console sometimes runs lines together ("YAW_60 YAW_90", "YAW_60 [Timer] ...")
# and sometimes leaves out the line break after the echo for a while. So don't wait
# for whole lines: read what has arrived every 0.1 s and look for the token in it.
buf=
while :; do
    if IFS= read -r -t 0.1 chunk <&"$LOGFD"; then
        handle "$buf$chunk" 1
        buf=
    else
        [ $? -gt 128 ] || break  # end of input, not a timeout
        buf+=$chunk
        [ -n "$buf" ] && handle "$buf" 0 && buf=
    fi
done
