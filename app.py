#!/usr/bin/env python3
"""Source Yaw: pick the cl_yawspeed cycle key, the yawspeeds and their crosshair colours."""

import io
import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import yawcore as core  # noqa: E402

APP_ID = "io.github.soulmanyes.SourceYaw"

# GDK key names -> Source bind names, for keys whose names differ
GDK_TO_SOURCE = {
    "Return": "enter", "Escape": "escape", "BackSpace": "backspace", "Tab": "tab",
    "ISO_Left_Tab": "tab", "Caps_Lock": "capslock", "Shift_L": "shift",
    "Shift_R": "rshift", "Control_L": "ctrl", "Control_R": "rctrl", "Alt_L": "alt",
    "Alt_R": "ralt", "ISO_Level3_Shift": "ralt", "Super_L": "lwin", "Super_R": "rwin",
    "Menu": "app", "Insert": "ins", "Delete": "del", "Home": "home", "End": "end",
    "Page_Up": "pgup", "Prior": "pgup", "Page_Down": "pgdn", "Next": "pgdn",
    "Up": "uparrow", "Down": "downarrow", "Left": "leftarrow", "Right": "rightarrow",
    "Pause": "pause", "Scroll_Lock": "scrolllock", "Num_Lock": "numlock",
    "KP_0": "kp_ins", "KP_Insert": "kp_ins", "KP_1": "kp_end", "KP_End": "kp_end",
    "KP_2": "kp_downarrow", "KP_Down": "kp_downarrow", "KP_3": "kp_pgdn",
    "KP_Next": "kp_pgdn", "KP_Page_Down": "kp_pgdn", "KP_4": "kp_leftarrow",
    "KP_Left": "kp_leftarrow", "KP_5": "kp_5", "KP_Begin": "kp_5",
    "KP_6": "kp_rightarrow", "KP_Right": "kp_rightarrow", "KP_7": "kp_home",
    "KP_Home": "kp_home", "KP_8": "kp_uparrow", "KP_Up": "kp_uparrow",
    "KP_9": "kp_pgup", "KP_Prior": "kp_pgup", "KP_Page_Up": "kp_pgup",
    "KP_Enter": "kp_enter", "KP_Decimal": "kp_del", "KP_Delete": "kp_del",
    "KP_Divide": "kp_slash", "KP_Multiply": "kp_multiply", "KP_Subtract": "kp_minus",
    "KP_Add": "kp_plus", "semicolon": "semicolon", "apostrophe": "'", "grave": "`",
    "minus": "-", "equal": "=", "bracketleft": "[", "bracketright": "]",
    "backslash": "\\", "comma": ",", "period": ".", "slash": "/", "space": "space",
}
# fits the longest sound name (buttons/button17) plus the dropdown arrow
SOUND_WIDTH = 170

# GTK button numbers -> Source mouse names (GTK: 2 middle, 3 right, 8/9 side)
GTK_TO_MOUSE = {1: "mouse1", 2: "mouse3", 3: "mouse2", 8: "mouse4", 9: "mouse5"}


def source_key(keyval, keycode, display):
    # use the unshifted key, so shift+1 still means "1"
    ok, keys, vals = display.map_keycode(keycode)
    if ok and vals:
        keyval = vals[0]
    name = Gdk.keyval_name(keyval) or ""
    if name in GDK_TO_SOURCE:
        return GDK_TO_SOURCE[name]
    if name.lower() in core.VALID_KEYS:
        return name.lower()
    return None


# ---------------------------------------------------------------- older GTK / libadwaita
# Debian 12 and Ubuntu 22.04 (Mint 21) ship libadwaita 1.1-1.2 and GTK 4.6-4.8. The
# newer widgets are used where they exist, with plain stand-ins otherwise.

def adw_at_least(minor):
    return (Adw.get_major_version(), Adw.get_minor_version()) >= (1, minor)


GTK_4_10 = (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4, 10)


def toolbar_view(top_bars, content):
    """Header bars stacked above content (Adw.ToolbarView is libadwaita 1.4+)."""
    if adw_at_least(4):
        view = Adw.ToolbarView()
        for bar in top_bars:
            view.add_top_bar(bar)
        view.set_content(content)
        return view
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    for bar in top_bars:
        box.append(bar)
    content.set_vexpand(True)
    box.append(content)
    return box


class _PlainBanner(Gtk.Revealer):
    """Stand-in for Adw.Banner (libadwaita 1.3+): a warning line under the header."""

    def __init__(self):
        super().__init__()
        self.label = Gtk.Label(wrap=True, margin_top=8, margin_bottom=8,
                               margin_start=12, margin_end=12)
        self.label.add_css_class("warning")
        self.set_child(self.label)

    def set_title(self, text):
        self.label.set_label(text)

    def get_title(self):
        return self.label.get_label()

    def set_revealed(self, revealed):
        self.set_reveal_child(revealed)


def make_banner():
    return Adw.Banner() if adw_at_least(3) else _PlainBanner()


if adw_at_least(4):
    SwitchRow = Adw.SwitchRow
else:
    class SwitchRow(Adw.ActionRow):
        """Stand-in for Adw.SwitchRow (libadwaita 1.4+)."""
        active = GObject.Property(type=bool, default=False)

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            self.add_suffix(switch)
            self.set_activatable_widget(switch)
            self.bind_property("active", switch, "active",
                               GObject.BindingFlags.BIDIRECTIONAL
                               | GObject.BindingFlags.SYNC_CREATE)

        def get_active(self):
            return self.active

        def set_active(self, value):
            self.active = value


if adw_at_least(5):
    DialogBase = Adw.Dialog
else:
    class DialogBase(Adw.Window):
        """Stand-in for Adw.Dialog (libadwaita 1.5+): a small modal window."""

        def __init__(self, title, content_width, content_height):
            super().__init__(title=title, default_width=content_width,
                             default_height=content_height, modal=True)

        def set_child(self, child):
            self.set_content(child)

        def present(self, parent=None):
            if parent:
                self.set_transient_for(parent)
            super().present()


def color_button():
    if GTK_4_10:
        return Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
    button = Gtk.ColorButton()  # GTK 4.6-4.8
    button.set_use_alpha(False)
    return button


def pick_png(parent, title, folder, on_path):
    """Asks for a PNG file and calls on_path(path), or on_path(None) when cancelled."""
    png = Gtk.FileFilter(name="PNG images")
    png.add_mime_type("image/png")
    if GTK_4_10:
        dialog = Gtk.FileDialog(title=title)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(png)
        dialog.set_filters(filters)
        if folder:
            dialog.set_initial_folder(Gio.File.new_for_path(str(folder)))

        def done(dlg, result):
            try:
                on_path(dlg.open_finish(result).get_path())
            except GLib.Error:
                on_path(None)  # cancelled
        dialog.open(parent, None, done)
        return
    chooser = Gtk.FileChooserNative(title=title, transient_for=parent,
                                    action=Gtk.FileChooserAction.OPEN)
    chooser.add_filter(png)
    if folder:
        chooser.set_current_folder(Gio.File.new_for_path(str(folder)))

    def response(dlg, answer):
        on_path(dlg.get_file().get_path() if answer == Gtk.ResponseType.ACCEPT else None)
        parent.file_chooser = None
    chooser.connect("response", response)
    parent.file_chooser = chooser  # a native chooser must be kept alive while open
    chooser.show()


# the game switch picks one of two games, not on/off, so both sides look the same
APP_CSS = """
switch.game-switch:checked, switch.game-switch:checked:hover {
    background-color: alpha(currentColor, 0.15);
}
switch.game-switch:checked > slider { background-color: white; }
"""


def load_app_css():
    provider = Gtk.CssProvider()
    try:
        if hasattr(provider, "load_from_string"):  # GTK 4.12+
            provider.load_from_string(APP_CSS)
        else:
            provider.load_from_data(APP_CSS.encode())
    except (TypeError, GLib.Error):
        try:
            provider.load_from_data(APP_CSS, -1)  # signature on some older PyGObject
        except (TypeError, GLib.Error):
            return  # only looks: the switch keeps its normal colours
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def texture_from_image(im, size):
    im = im.resize((size, size), resample=0)  # nearest: keep crosshair pixels sharp
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(buf.getvalue()))


def hex_color(rgba):
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in (rgba.red, rgba.green, rgba.blue))


class KeyCaptureDialog(DialogBase):
    """Waits for one key, mouse button or wheel turn and reports its Source name."""

    def __init__(self, on_key):
        super().__init__(title="Cycle key", content_width=360, content_height=220)
        self.on_key = on_key
        self.label = Gtk.Label(label="Press a key, mouse button or scroll\ninside this box",
                               justify=Gtk.Justification.CENTER, vexpand=True, hexpand=True)
        area = Gtk.Frame(child=self.label, margin_start=18, margin_end=18,
                         margin_top=6, margin_bottom=18, focusable=True)
        area.add_css_class("view")
        self.set_child(toolbar_view([Adw.HeaderBar()], area))

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.key_pressed)
        self.add_controller(keys)
        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self.clicked)
        area.add_controller(click)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self.scrolled)
        area.add_controller(scroll)
        self.set_focus(area)

    def done(self, key):
        if key:
            self.on_key(key)
            self.close()
        else:
            self.label.set_label("CS:S has no bind name for that key,\ntry another")

    def key_pressed(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        self.done(source_key(keyval, keycode, ctrl.get_widget().get_display()))
        return True

    def clicked(self, gesture, n, x, y):
        self.done(GTK_TO_MOUSE.get(gesture.get_current_button()))

    def scrolled(self, ctrl, dx, dy):
        if dy:
            self.done("mwheelup" if dy < 0 else "mwheeldown")
        return True


class EntryRow(Adw.ActionRow):
    """One yawspeed: drag handle, start choice, crosshair preview, speed, colour, sound, remove."""

    def __init__(self, window, entry):
        super().__init__()
        self.window = window

        # drag the handle onto another row to take its place in the cycle
        handle = Gtk.Image(icon_name="sourceyaw-drag-handle-symbolic", tooltip_text="Drag to reorder")
        handle.set_cursor(Gdk.Cursor.new_from_name("grab"))
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", self.drag_prepare)
        drag.connect("drag-begin", self.drag_begin)
        handle.add_controller(drag)
        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect("drop", self.dropped)
        self.add_controller(drop)

        # radio: which yawspeed the game starts on (grouped with the first row's)
        self.start = Gtk.CheckButton(valign=Gtk.Align.CENTER,
                                     tooltip_text="Start the game on this yawspeed")
        if window.rows:
            self.start.set_group(window.rows[0].start)
        self.start.connect("toggled", lambda b: b.get_active() and window.changed())

        # fixed size: a Picture would stretch into whatever space the row has left
        self.preview = Gtk.Image(pixel_size=33, valign=Gtk.Align.CENTER)

        # one box so the order is fixed (add_prefix puts each new widget first)
        prefix = Gtk.Box(spacing=12)
        for widget in (handle, self.start, self.preview):
            prefix.append(widget)
        self.add_prefix(prefix)

        self.speed = Gtk.SpinButton.new_with_range(1, 2000, 10)
        self.speed.set_digits(4)
        # room for e.g. 293.9535, and show 210 rather than 210.0000
        self.speed.set_width_chars(8)
        self.speed.connect("output", self.format_speed)
        self.speed.set_valign(Gtk.Align.CENTER)
        self.speed.set_value(float(entry["speed"]))
        self.speed.set_tooltip_text("cl_yawspeed")
        self.speed.connect("value-changed", lambda *_: window.changed())
        self.add_suffix(self.speed)

        self.color = color_button()
        self.color.set_valign(Gtk.Align.CENTER)
        rgba = Gdk.RGBA()
        rgba.parse(entry["color"])
        self.color.set_rgba(rgba)
        self.color.set_tooltip_text("Crosshair colour")
        self.color.connect("notify::rgba", lambda *_: (self.update_preview(), window.changed()))
        self.add_suffix(self.color)

        self.choices = list(window.sound_choices)
        sound = entry.get("sound") or ""
        if sound not in [v for v, _ in self.choices]:
            # set by hand or missing from this install; keep it rather than drop it
            self.choices.append((sound, sound))
        self.sound = Gtk.DropDown(model=Gtk.StringList.new([l for _, l in self.choices]))
        # closed: just the name; open list: name, a play button and the selected tick,
        # so sounds can be tried without closing the menu
        self.sound.set_factory(self.sound_factory(in_list=False))
        self.sound.set_list_factory(self.sound_factory(in_list=True))
        self.ticks = []
        self.sound.set_valign(Gtk.Align.CENTER)
        # same width in every row so the columns line up, whatever the sound name
        self.sound.set_size_request(SOUND_WIDTH, -1)
        self.sound.set_tooltip_text("Sound when switching to this yawspeed")
        self.sound.set_selected([v for v, _ in self.choices].index(sound))
        self.sound.connect("notify::selected", self.sound_changed)
        self.add_suffix(self.sound)

        remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                            tooltip_text="Remove")
        remove.add_css_class("flat")
        remove.connect("clicked", lambda *_: window.remove_entry(self))
        self.add_suffix(remove)
        self.update_preview()

    def drag_prepare(self, source, x, y):
        index = str(self.window.rows.index(self))
        return Gdk.ContentProvider.new_for_value(GObject.Value(GObject.TYPE_STRING, index))

    def drag_begin(self, source, drag):
        source.set_icon(Gtk.WidgetPaintable(widget=self), 0, 0)

    def dropped(self, target, value, x, y):
        self.window.move_entry(int(value), self.window.rows.index(self))
        return True

    def sound_factory(self, in_list):
        factory = Gtk.SignalListItemFactory()

        def setup(_, item):
            box = Gtk.Box(spacing=6)
            label = Gtk.Label(xalign=0, hexpand=True)
            box.append(label)
            if in_list:
                play = Gtk.Button(icon_name="media-playback-start-symbolic",
                                  tooltip_text="Play this sound")
                play.add_css_class("flat")
                play.connect("clicked", lambda *_: self.play_sound(item.get_position()))
                tick = Gtk.Image(icon_name="object-select-symbolic")
                box.append(play)
                box.append(tick)
                self.ticks.append((item, play, tick))
            item.set_child(box)

        def bind(_, item):
            box = item.get_child()
            box.get_first_child().set_label(item.get_item().get_string())
            if in_list:
                self.update_ticks()

        factory.connect("setup", setup)
        factory.connect("bind", bind)
        return factory

    def update_ticks(self):
        selected = self.sound.get_selected()
        for item, play, tick in self.ticks:
            pos = item.get_position()
            # "None" has nothing to play
            play.set_visible(pos != Gtk.INVALID_LIST_POSITION and bool(self.choices[pos][0]))
            tick.set_opacity(1 if pos == selected else 0)

    def sound_changed(self, *_):
        self.update_ticks()
        self.window.changed()

    def play_sound(self, index):
        sound = self.choices[index][0]
        if not (self.window.cstrike
                and core.play_sound(self.window.cstrike, sound, self.window.game)):
            self.window.toasts.add_toast(Adw.Toast(
                title=f"Couldn't find {sound} in your game files", timeout=3))

    def format_speed(self, spin):
        spin.set_text(core.fmt_speed(spin.get_value()))
        return True

    def value(self):
        return {"speed": round(self.speed.get_value(), 4),
                "color": hex_color(self.color.get_rgba()),
                "sound": self.choices[self.sound.get_selected()][0] or None}

    def update_preview(self):
        if self.window.base:
            im = core.recolor(self.window.base, hex_color(self.color.get_rgba()))
            self.preview.set_from_paintable(texture_from_image(im, 33))


class Window(Adw.ApplicationWindow):
    def __init__(self, app, game=None):
        super().__init__(application=app, title="Source Yaw")
        self.set_default_size(620, 640)
        installed = core.installed_games()
        if game is None:
            game = core.last_game()
            if game not in installed and installed:
                game = installed[0]
        self.game = game
        self.info = core.GAMES[game]
        # Momentum sets its own crosshair colour from yaws.cfg; CS:S goes through KROSSHAIR
        self.uses_krosshair = self.info["colors"] == "krosshair"
        self.cstrike = core.find_game(game)  # the game's mod folder (cstrike, momentum)
        self.data = core.load_settings(game)
        self.base_choice = self.data["base"]
        self.base = core.resolve_base(self.data) if self.uses_krosshair else core.plain_cross()
        sounds = core.available_sounds(self.cstrike, game) if self.cstrike else core.SOUNDS
        self.sound_choices = [("", "None")] + [(s, s) for s in sounds]
        self.rows = []

        self.toasts = Adw.ToastOverlay()
        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(
            title="Source Yaw", subtitle=f"{self.info['name']} · Version {core.VERSION}")
        header.set_title_widget(self.title_widget)
        self.apply_btn = Gtk.Button(label="Apply")
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", self.apply)
        header.pack_end(self.apply_btn)
        self.banner = make_banner()

        page = Adw.PreferencesPage()
        self.toasts.set_child(page)
        self.set_content(toolbar_view([header, self.banner], self.toasts))

        game_group = Adw.PreferencesGroup(title="Game")
        if len(installed) > 1:
            self.game_ids = installed
            current = installed.index(game) if game in installed else 0
            if len(installed) == 2:
                # two games: a switch with one game on each side
                self.game_row = Adw.ActionRow(title="Game",
                                              subtitle="Each game has its own settings")
                self.game_switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=current == 1)
                self.game_switch.add_css_class("game-switch")
                sides = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER)
                for i, side in enumerate(installed):
                    label = Gtk.Label(label=core.GAMES[side]["short"])
                    if i != current:
                        label.add_css_class("dim-label")  # the side that isn't picked
                    sides.append(label)
                    if i == 0:
                        sides.append(self.game_switch)
                self.game_row.add_suffix(sides)
                self.game_switch.connect("notify::active", self.switch_game)
            else:
                self.game_switch = None
                self.game_row = Adw.ComboRow(title="Game",
                                             subtitle="Each game has its own settings")
                self.game_row.set_model(Gtk.StringList.new(
                    [core.GAMES[g]["name"] for g in installed]))
                self.game_row.set_selected(current)
                self.game_row.connect("notify::selected", self.switch_game)
            game_group.add(self.game_row)
        self.autoexec_row = SwitchRow(
            title="Load from autoexec.cfg",
            subtitle="Adds exec yaws.cfg to your autoexec.cfg, so the game loads your "
                     "yawspeed binds when it starts")
        self.autoexec_row.set_active(bool(self.cstrike) and core.autoexec_runs_yaws(self.cstrike))
        self.autoexec_row.set_sensitive(bool(self.cstrike))
        self.autoexec_row.connect("notify::active", self.toggle_autoexec)
        game_group.add(self.autoexec_row)
        page.add(game_group)

        keys = Adw.PreferencesGroup(title="Keybind")
        self.key_row = Adw.ActionRow(title="Cycle key")
        self.key_text = Gtk.Label(valign=Gtk.Align.CENTER)
        self.key_text.add_css_class("heading")
        self.key_row.add_suffix(self.key_text)
        change = Gtk.Button(label="Change…", valign=Gtk.Align.CENTER)
        change.connect("clicked", self.capture_key)
        self.key_row.add_suffix(change)
        keys.add(self.key_row)
        page.add(keys)

        self.speeds = Adw.PreferencesGroup(
            title="Yawspeeds",
            description="Cycled in this order. The ticked one is set when the game starts.")
        add = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER,
                         tooltip_text="Add a yawspeed")
        add.add_css_class("flat")
        add.connect("clicked", self.add_entry)
        self.speeds.set_header_suffix(add)
        page.add(self.speeds)

        cross = Adw.PreferencesGroup(title="Crosshair")
        self.color_row = SwitchRow(
            title="Change crosshair colour",
            subtitle="Shows a KROSSHAIR crosshair in the colour of the current yawspeed"
            if self.uses_krosshair else
            f"Sets {self.info['name']}'s own crosshair to the colour of the current yawspeed")
        self.color_row.set_active(self.data["crosshair"])
        self.color_row.connect("notify::active", lambda *_: self.changed())
        cross.add(self.color_row)
        page.add(cross)
        if self.uses_krosshair:
            self.add_krosshair_rows(cross)
            self.add_steam_group(page)

        self.key = self.data["key"]
        self.key_text.set_label(self.key)
        self.show_key_conflicts()
        for entry in self.data["entries"]:
            self.add_entry(entry=entry)
        self.rows[self.data["start"]].start.set_active(True)
        self.check_setup()
        self.set_dirty(False)

    def add_krosshair_rows(self, cross):
        self.base_row = Adw.ComboRow(
            title="Crosshair",
            subtitle="Every visible pixel gets the yawspeed's colour, so outlines "
                     "lose their own colour")
        self.base_row.connect("notify::selected", self.base_selected)
        cross.add(self.base_row)
        self.fill_base_row()

        self.krosshair_row = Adw.ActionRow(title="KROSSHAIR")
        self.krosshair_btn = Gtk.Button(label="Install", valign=Gtk.Align.CENTER)
        self.krosshair_btn.connect("clicked", self.install_krosshair)
        self.krosshair_row.add_suffix(self.krosshair_btn)
        cross.add(self.krosshair_row)
        self.show_krosshair()

    def add_steam_group(self, page):
        steam = Adw.PreferencesGroup(
            title="Steam launch options",
            description="CS:S Properties → Launch Options. sourceyaw-run applies these "
                        "settings and runs the colour changer while the game is open.")
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text="Read the launch options from Steam again")
        refresh.add_css_class("flat")
        refresh.connect("clicked", lambda *_: self.show_launch_option())
        steam.set_header_suffix(refresh)
        self.launch_row = Adw.ActionRow(title_selectable=True)
        self.launch_row.add_css_class("monospace")
        copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text="Copy")
        copy.add_css_class("flat")
        copy.connect("clicked", lambda *_: self.copy(self.launch_option))
        self.launch_row.add_suffix(copy)
        steam.add(self.launch_row)
        page.add(steam)
        self.show_launch_option()

    # ------------------------------------------------------------ state

    def check_setup(self):
        problem = None
        if not self.cstrike and core.flatpak_steam_only(self.game):
            problem = ("Flatpak Steam isn't supported: sourceyaw-run can't run inside "
                       "its sandbox. Use Steam from your distro's packages")
        elif not self.cstrike:
            problem = f"{self.info['name']} not found in your Steam libraries"
        self.banner.set_title(problem or "")
        self.banner.set_revealed(bool(problem))
        self.apply_btn.set_sensitive(bool(self.cstrike))

    # ------------------------------------------------------------ crosshair

    def base_options(self):
        options = []
        cm = core.crosshair_maker_png()
        if cm:
            options.append(("crosshair-maker", f"crosshair-maker: {cm.stem}"))
        options.append(("builtin", "Plain cross"))
        if self.base_choice not in ("crosshair-maker", "builtin"):
            options.append((self.base_choice, os.path.basename(self.base_choice)))
        options.append(("pick", "Choose an image…"))
        return options

    def fill_base_row(self):
        self.base_opts = self.base_options()
        values = [v for v, _ in self.base_opts]
        # an unavailable choice (crosshair-maker gone) shows what is used instead
        current = self.base_choice if self.base_choice in values else "builtin"
        self.filling = True
        self.base_row.set_model(Gtk.StringList.new([label for _, label in self.base_opts]))
        self.base_row.set_selected(values.index(current))
        self.filling = False

    def base_selected(self, *_):
        if self.filling:
            return
        value = self.base_opts[self.base_row.get_selected()][0]
        if value == "pick":
            self.pick_image()
        else:
            self.set_base(value)

    def pick_image(self):
        def done(path):
            if path:
                self.set_base(path)
            self.fill_base_row()

        pick_png(self, "Choose a crosshair image", core.krosshair_crosshairs(), done)

    def set_base(self, choice):
        self.base_choice = choice
        self.base = core.resolve_base({"base": choice})
        for row in self.rows:
            row.update_preview()
        self.changed()

    def switch_game(self, widget, _):
        index = int(widget.get_active()) if self.game_switch else widget.get_selected()
        game = self.game_ids[index]
        if game == self.game:
            return
        if self.dirty:
            # each game has its own settings; don't drop unapplied changes silently
            self.toasts.add_toast(Adw.Toast(title="Apply your changes before switching game",
                                            timeout=4))
            widget.handler_block_by_func(self.switch_game)
            back = self.game_ids.index(self.game)
            if self.game_switch:
                widget.set_active(bool(back))
            else:
                widget.set_selected(back)
            widget.handler_unblock_by_func(self.switch_game)
            return
        core.set_last_game(game)
        Window(self.get_application(), game).present()
        self.destroy()

    def toggle_autoexec(self, row, _):
        on = row.get_active()
        try:
            core.set_autoexec(self.cstrike, on)
        except OSError as e:
            self.toasts.add_toast(Adw.Toast(title=f"Couldn't change autoexec.cfg: {e.strerror}",
                                            timeout=5))
            row.handler_block_by_func(self.toggle_autoexec)
            row.set_active(not on)
            row.handler_unblock_by_func(self.toggle_autoexec)
            return
        self.toasts.add_toast(Adw.Toast(
            title="Added to autoexec.cfg" if on else "Removed from autoexec.cfg", timeout=3))

    def show_krosshair(self):
        manifest = core.krosshair_installed()
        if manifest:
            self.krosshair_row.set_subtitle(f"Installed ({manifest})")
        elif core.can_install_krosshair():
            self.krosshair_row.set_subtitle(
                f"Not installed. Install downloads KROSSHAIR {core.KROSSHAIR_VERSION} "
                "(GPL-3.0) from github.com/noahlyk/krosshair into your user folder. "
                "No password needed.")
        else:
            self.krosshair_row.set_subtitle(
                "Not installed. Get it from github.com/noahlyk/krosshair")
        self.krosshair_btn.set_visible(not manifest and core.can_install_krosshair())

    def install_krosshair(self, *_):
        self.krosshair_btn.set_sensitive(False)
        self.krosshair_btn.set_label("Installing…")

        def work():
            try:
                core.install_krosshair()
                error = None
            except Exception as e:  # network, checksum, disk: all shown to the user
                error = str(e)
            GLib.idle_add(finished, error)

        def finished(error):
            self.krosshair_btn.set_sensitive(True)
            self.krosshair_btn.set_label("Install")
            self.show_krosshair()
            self.toasts.add_toast(Adw.Toast(
                title=f"Couldn't install KROSSHAIR: {error}" if error
                else "KROSSHAIR installed. It works the next time you start CS:S",
                timeout=5))
            return False

        threading.Thread(target=work, daemon=True).start()

    def set_dirty(self, dirty):
        self.dirty = dirty
        title = "Source Yaw" + (" •" if dirty else "")
        self.set_title(title)
        self.title_widget.set_title(title)

    def changed(self):
        self.set_dirty(True)

    def collect(self):
        start = next((i for i, row in enumerate(self.rows) if row.start.get_active()), 0)
        return {"key": self.key, "crosshair": self.color_row.get_active(), "start": start,
                "base": self.base_choice,
                # Momentum: the user's own crosshair colour, put back when colours are off
                "original_color": self.data.get("original_color"),
                "entries": [row.value() for row in self.rows]}

    # ------------------------------------------------------------ actions

    def show_key_conflicts(self):
        conflicts = core.key_conflicts(self.cstrike, self.key) if self.cstrike else []
        if not conflicts:
            self.key_row.set_subtitle("Each press switches to the next yawspeed")
            return
        commands = sorted({cmd for _, cmd in conflicts})
        text = f"⚠ {self.key} is bound to {', '.join(commands)} now. Apply replaces that"
        if any(name == "autoexec.cfg" for name, _ in conflicts):
            text += ", but the bind in autoexec.cfg may still win if it comes after exec yaws.cfg"
        self.key_row.set_subtitle(GLib.markup_escape_text(text))

    def capture_key(self, *_):
        def got(key):
            self.key = key
            self.key_text.set_label(key)
            self.show_key_conflicts()
            self.changed()
        KeyCaptureDialog(got).present(self)

    def add_entry(self, *_, entry=None):
        if entry is None:
            last = self.rows[-1].value() if self.rows else {"speed": 90, "sound": None}
            entry = {"speed": last["speed"] + 60, "color": "#00aaff", "sound": None}
            self.changed()
        row = EntryRow(self, entry)
        self.rows.append(row)
        self.speeds.add(row)
        self.renumber()

    def remove_entry(self, row):
        was_start = row.start.get_active()
        self.rows.remove(row)
        self.speeds.remove(row)
        if self.rows and was_start:
            self.rows[0].start.set_active(True)
        self.renumber()
        self.changed()

    def move_entry(self, src, dst):
        if src == dst:
            return
        self.rows.insert(dst, self.rows.pop(src))
        # PreferencesGroup can only append, so re-add the rows in the new order
        for row in self.rows:
            self.speeds.remove(row)
        for row in self.rows:
            self.speeds.add(row)
        self.renumber()
        self.changed()

    def renumber(self):
        for i, row in enumerate(self.rows):
            row.set_title(str(i + 1))

    def apply(self, *_):
        data = self.collect()
        problems = core.validate(data)
        if problems:
            self.toasts.add_toast(Adw.Toast(title=problems[0], timeout=4))
            return
        try:
            notes = core.apply(data, self.cstrike, game=self.game)
        except OSError as e:
            self.toasts.add_toast(Adw.Toast(title=f"Not saved: {e.strerror}", timeout=5))
            return
        self.set_dirty(False)
        for note in notes:
            self.toasts.add_toast(Adw.Toast(title=note, timeout=4))
        self.toasts.add_toast(Adw.Toast(
            title="Saved. Game already open? Run: exec yaws", timeout=6))

    def show_launch_option(self):
        current = core.current_launch_options(self.game)
        run = core.runner()
        self.launch_option, already = core.launch_option(current, run)
        self.launch_row.set_title(GLib.markup_escape_text(self.launch_option))
        if current is None:
            note = "Couldn't read your Steam launch options. Put sourceyaw-run before %command%"
        elif already:
            note = "Already set up"
        elif current:
            note = "Your current launch options with sourceyaw-run added. Replace them with this"
        else:
            note = "You have no launch options yet. Paste this in"
        if run != core.RUNNER:
            note += ". Steam can't find sourceyaw-run by name here, so this uses the full path"
        self.launch_row.set_subtitle(note)

    def copy(self, text):
        # set_content works on every PyGObject; Clipboard.set(str) needs a newer one
        self.get_display().get_clipboard().set_content(Gdk.ContentProvider.new_for_value(text))
        self.toasts.add_toast(Adw.Toast(title="Copied", timeout=2))


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        # our own icons: the app icon, and a drag handle (themes like Papirus have none)
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(
            os.path.join(os.path.dirname(os.path.realpath(__file__)), "icons"))
        Gtk.Window.set_default_icon_name(APP_ID)
        load_app_css()
        core.migrate_old_name()
        win = self.get_active_window() or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
