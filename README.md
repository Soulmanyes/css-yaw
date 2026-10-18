# CS:S Yaw

Cycle `cl_yawspeed` in Counter-Strike: Source with one key, and see which yawspeed is
active from a sound and from your crosshair colour. Made for surf on Linux.

You can't print to chat without annoying everyone, `developer 1` is cheat-protected
on servers, and a desktop popup over a fullscreen game makes it stutter. So CS:S Yaw
tells you the yawspeed two other ways:

- **Sound:** a short game sound plays when you switch, and only you hear it.
- **Crosshair colour:** your [KROSSHAIR](https://github.com/fibsussy/krosshair) crosshair
  changes colour for each yawspeed. KROSSHAIR draws inside the game's own frames, so this
  adds no overlay and no stutter.

## What you need

- Linux, and the native Linux version of CS:S on Steam.
- Python 3, GTK 4, libadwaita 1.5 or newer, PyGObject and Pillow. `install.sh` installs
  them if they are missing.
- For the crosshair colours: KROSSHAIR with a crosshair picked in crosshair-maker, and
  `KROSSHAIR=1` in your launch options.

## Install

```sh
./install.sh
```

Then:

1. Make sure your `autoexec.cfg` has the line `exec yaws.cfg`.
2. Open **CS:S Yaw**, pick your key, yawspeeds, colours and sounds, and press **Apply**.
3. Add `css-yaw-run` right before `%command%` in the CS:S launch options. The app shows
   your current launch options with it added, ready to copy, for example:

   ```
   KROSSHAIR=1 css-yaw-run %command%
   ```

To remove the app, run `./install.sh --uninstall` and take `css-yaw-run` out of the
launch options.

## In the app

- **Cycle key:** press any key, mouse button or wheel direction to bind it.
- **Yawspeeds:** add, remove or drag them into order. Each one has a crosshair colour and a
  sound, which you can preview from the dropdown. The ticked one is set when the game starts.
- **Change crosshair colour:** turn the colour changing off if you only want the sounds.

If the game is already running when you press Apply, run `exec yaws` in the console.

## How it works

- The app writes `cfg/yaws.cfg`. In it, each press sets the next `cl_yawspeed`, plays its
  sound with `play`, and runs `echo YAW_<speed>`. `con_logfile yaw.log` copies the console
  to a file.
- `css-yaw-run` wraps the game. It rebuilds `yaws.cfg` and the coloured crosshairs from
  your settings, then watches `yaw.log` while the game runs. On each `YAW_<speed>` line, it
  copies that colour over crosshair-maker's `current.png`. KROSSHAIR reloads that file
  whenever it changes.
- When the game exits, `css-yaw-run` puts your normal crosshair back.

Settings and generated images are stored in `~/.config/css-yaw`.

## Limits

- Recolouring is flat: every visible pixel of the crosshair gets the chosen colour, so
  outlines lose their own colour.
- If another config changes `cl_yawspeed` directly, the colour isn't updated until the
  next press of the cycle key.

## License

[CC0 1.0](LICENSE). Public domain, do what you like. CS:S Yaw ships no game files: it
plays sounds straight from your own CS:S install.
