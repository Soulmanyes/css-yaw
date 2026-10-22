# Source Yaw overlay

A Vulkan layer that draws the strafe trainer's offset over the game. It is a fork of
[KROSSHAIR](https://github.com/fibsussy/krosshair) v0.2.5 (commit f6e875a), by its authors,
and is licensed under the [GPL-3.0](LICENSE) like the original. The rest of Source Yaw is
CC0; this folder is a separate program.

Changes from KROSSHAIR:

- Draws a short text from a glyph atlas (`SOURCEYAW_OVERLAY_ATLAS`) instead of a crosshair.
- Reads the text, its colour row and its place from a small shared state file
  (`SOURCEYAW_OVERLAY_STATE`) every frame, so nothing is reloaded while the game runs.
- Does nothing, and leaves the game's frame untouched, while the text is hidden.
- Renamed to `VK_LAYER_SOURCEYAW_overlay`, enabled by `SOURCEYAW_OVERLAY=1`, with its own
  entry points, so it can run beside KROSSHAIR. No dynamic effect masks.

The state file layout is documented in `src/layer.c` (search for `struct sy_state`).

Build: `make` (uses the bundled Vulkan headers). `install.sh` in the main folder builds and
installs it.

Bundled third-party files:

- `include/vulkan/`, `include/vk_video/`: Vulkan-Headers by The Khronos Group,
  Apache-2.0 OR MIT, see `include/LICENSES-vulkan-headers/`.
- `include/stb_image.h`: stb_image by Sean Barrett, public domain or MIT (see the end of the
  file).
