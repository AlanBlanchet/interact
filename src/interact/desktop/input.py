"""Cross-platform desktop input — the "deeper driver" leg.

Input injection uses the deepest portable Linux path: a ``/dev/uinput`` **absolute
virtual touchscreen** (``INPUT_PROP_DIRECT`` + ``ABS_X/ABS_Y``) via python-evdev.
libinput projects its coordinates onto the screen identically on **X11 and Wayland**
(GNOME / KDE / wlroots) — true absolute positioning, avoiding the relative-touchpad
demotion that breaks ``ydotool --absolute``. One driver for both display servers.

Requires ``/dev/uinput`` access — a udev rule plus membership of the ``input`` group,
no root (``interact doctor`` checks this). Linux-only; ``evdev`` is imported lazily so
this module imports everywhere. Capture and window enumeration stay per-display-server
(maim on X11, xdg-desktop-portal on Wayland) and are layered on top separately.

Coordinates are screen pixels; map other spaces in via :class:`interact.frames.Frame`.
"""

import glob
import os
import time


ABS_MAX = 32767
_BUTTONS = {"left": 1, "middle": 2, "right": 3}


def screen_to_abs(
    x: float, y: float, screen_w: int, screen_h: int, abs_max: int = ABS_MAX
) -> tuple[int, int]:
    """Map a screen-pixel point into a uinput absolute device's ``0..abs_max`` range.

    Pure — the testable core of absolute positioning. Clamps to the screen so an
    out-of-bounds detection can't fling the pointer off-screen.
    """
    if screen_w <= 0 or screen_h <= 0:
        return 0, 0
    cx = min(max(x, 0.0), float(screen_w))
    cy = min(max(y, 0.0), float(screen_h))
    return round(cx / screen_w * abs_max), round(cy / screen_h * abs_max)


def kernel_input_device_names() -> list[str]:
    """Names of every input device the KERNEL currently exposes, read from sysfs.

    The display-server-agnostic way to confirm a uinput device was created. ``xinput list`` cannot
    do this job: under a Wayland session it enumerates only XWayland's own X11 devices, so a real,
    working ``interact-virtual-pointer`` is invisible there and a check built on it fails on a
    Wayland host while the device is perfectly fine (#79). Sysfs is populated by the kernel at
    ``UI_DEV_CREATE``, identically under Xorg and Wayland, and needs no root.

    (Confirming libinput has *claimed* the device is a further step — `libinput list-devices`,
    which needs root. Creation is what a test can assert unprivileged.)
    """
    names: list[str] = []
    for path in sorted(glob.glob("/sys/class/input/event*/device/name")):
        try:
            with open(path) as f:
                names.append(f.read().strip())
        except OSError:
            continue  # device disappeared between glob and read — normal hotplug race
    return names


def _keyboard_codes(ecodes) -> list[int]:
    """evdev key codes the virtual keyboard declares — letters, digits, and the common
    editing/modifier keys ``type_text``/``key`` emit. A device can only send keys it
    declares at creation."""
    names = (
        [f"KEY_{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
        + [f"KEY_{d}" for d in "0123456789"]
        + [f"KEY_F{i}" for i in range(1, 13)]  # F1 was resolvable but never declared, so `key("F1")`
        + [                                    # wrote an event the kernel dropped, in silence (#115)
            "KEY_SPACE", "KEY_ENTER", "KEY_TAB", "KEY_BACKSPACE", "KEY_ESC", "KEY_DELETE",
            "KEY_MINUS", "KEY_EQUAL", "KEY_DOT", "KEY_COMMA", "KEY_SLASH", "KEY_SEMICOLON",
            "KEY_APOSTROPHE", "KEY_LEFTBRACE", "KEY_RIGHTBRACE", "KEY_BACKSLASH", "KEY_GRAVE",
            # Every modifier `_UINPUT_MODIFIERS` can produce must be here or the chord arrives
            # UNMODIFIED — KEY_LEFTMETA was missing, so every `super+`/`cmd+` chord was a no-op.
            "KEY_LEFTSHIFT", "KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_LEFTMETA",
            "KEY_RIGHTSHIFT", "KEY_RIGHTCTRL", "KEY_RIGHTALT",
            "KEY_HOME", "KEY_END", "KEY_PAGEUP", "KEY_PAGEDOWN", "KEY_INSERT",
            "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT",
        ]
    )
    return [getattr(ecodes, n) for n in names if hasattr(ecodes, n)]


def _parse_chord(name: str) -> tuple[list[str], str]:
    """Split a key spec like ``"ctrl+shift+a"`` into (held modifiers, final key) — the shared
    grammar for every backend that synthesises a chord (uinput, pynput). A bare ``"a"`` → ([], "a")."""
    *mods, final = name.split("+")
    return mods, final


# Modifier token → evdev LEFT_* key name, for the uinput chord path.
_UINPUT_MODIFIERS = {
    "ctrl": "KEY_LEFTCTRL",
    "control": "KEY_LEFTCTRL",
    "shift": "KEY_LEFTSHIFT",
    "alt": "KEY_LEFTALT",
    "super": "KEY_LEFTMETA",
    "meta": "KEY_LEFTMETA",
    "cmd": "KEY_LEFTMETA",
}


class UinputPointer:
    """Absolute mouse + named-key input over ``/dev/uinput`` (X11 and Wayland).

    Declared as an ``INPUT_PROP_DIRECT`` touchscreen so libinput maps ``ABS_X/ABS_Y``
    onto the output. ``move``/``click``/``drag``/``scroll`` take screen-pixel coords;
    ``key`` presses a named ecode (``"KEY_ENTER"``, ``"KEY_TAB"``, …) — text typing
    is layout-dependent and handled separately.
    """

    def __init__(self, screen_w: int, screen_h: int, abs_max: int = ABS_MAX):
        try:
            from evdev import AbsInfo, UInput, ecodes
        except ImportError as exc:
            raise RuntimeError(
                "uinput input needs python-evdev (Linux only): `uv add evdev`"
            ) from exc

        self._ecodes = ecodes
        # Set BEFORE the device is opened, so the guard below can never silently no-op: it used to
        # read through a getattr default, which meant it did nothing at all wherever the attribute
        # was missing — including in most of its own tests.
        self._declared = set(_keyboard_codes(ecodes))
        self.screen_w, self.screen_h, self.abs_max = screen_w, screen_h, abs_max
        capabilities = {
            ecodes.EV_KEY: [
                ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE, ecodes.BTN_TOUCH,
            ],
            ecodes.EV_ABS: [
                (ecodes.ABS_X, AbsInfo(0, 0, abs_max, 0, 0, 0)),
                (ecodes.ABS_Y, AbsInfo(0, 0, abs_max, 0, 0, 0)),
            ],
            ecodes.EV_REL: [ecodes.REL_WHEEL, ecodes.REL_HWHEEL],
        }
        try:
            self._ui = UInput(
                capabilities,
                name="interact-virtual-pointer",
                input_props=[ecodes.INPUT_PROP_DIRECT],
            )
            # A SEPARATE keyboard node: the kernel drops key events a device never
            # declared, and a touchscreen (INPUT_PROP_DIRECT) + keyboard on one node
            # confuses libinput's classification — so typing/keys get their own device.
            self._kbd = UInput({ecodes.EV_KEY: sorted(self._declared)},
                               name="interact-virtual-keyboard")
        except (PermissionError, FileNotFoundError) as exc:
            raise RuntimeError(
                "cannot open /dev/uinput — add a udev rule and join the `input` group "
                "(no root); see `interact doctor`"
            ) from exc

    def move(self, x: float, y: float) -> None:
        ax, ay = screen_to_abs(x, y, self.screen_w, self.screen_h, self.abs_max)
        self._ui.write(self._ecodes.EV_ABS, self._ecodes.ABS_X, ax)
        self._ui.write(self._ecodes.EV_ABS, self._ecodes.ABS_Y, ay)
        self._ui.syn()

    def _btn_code(self, button: str) -> int:
        return {
            "left": self._ecodes.BTN_LEFT,
            "right": self._ecodes.BTN_RIGHT,
            "middle": self._ecodes.BTN_MIDDLE,
        }[button]

    def press(self, button: str = "left") -> None:
        self._ui.write(self._ecodes.EV_KEY, self._btn_code(button), 1)
        self._ui.syn()

    def release(self, button: str = "left") -> None:
        self._ui.write(self._ecodes.EV_KEY, self._btn_code(button), 0)
        self._ui.syn()

    def click(self, x: float, y: float, button: str = "left") -> None:
        self.move(x, y)
        self.press(button)
        time.sleep(0.02)
        self.release(button)

    def scroll(self, clicks: int, horizontal: bool = False) -> None:
        axis = self._ecodes.REL_HWHEEL if horizontal else self._ecodes.REL_WHEEL
        self._ui.write(self._ecodes.EV_REL, axis, clicks)
        self._ui.syn()

    def _key_code(self, token: str) -> int:
        """evdev code for a key token: a modifier name (ctrl/shift/alt/super) maps to its LEFT_*
        code, else KEY_<UPPER> (or a literal KEY_ name)."""
        name = _UINPUT_MODIFIERS.get(token.lower()) or (
            token if token.startswith("KEY_") else f"KEY_{token.upper()}"
        )
        return getattr(self._ecodes, name)

    def _check_declared(self, code, spec: str) -> None:
        """A uinput device may only emit codes it declared at creation; anything else the kernel
        discards without a word. That silence is the actual defect users report — the key simply
        does nothing and nothing points at why (#115)."""
        if code not in self._declared:
            raise ValueError(
                f"cannot send {spec!r}: not a key this virtual keyboard declares, so the kernel "
                "would discard it in silence. Letters, digits, F1-F12, the arrows, and "
                "ctrl/shift/alt/super are available."
            )

    def key(self, name: str) -> None:
        """Press a key or chord.

        Each transition gets its own SYN frame, which is what real hardware does: the modifier is
        latched, then the key arrives.

        It is NOT the explanation for #115, and an earlier version of this docstring said it was.
        The theory was that an atomic frame lets the key be evaluated against the modifier state
        from before it — but ``type_text`` below writes shift-down, key-down, key-up, shift-up and
        a SINGLE ``syn()``, and typing capitals is this module's most exercised path. If the theory
        held, every uppercase character would be broken. So the framing here is correctness for its
        own sake and costs nothing (frames are delimiters, not transactions); the cause of a
        declared chord arriving unmodified is still unconfirmed. The candidate not yet excluded is
        a settle race: X and libinput learn about the uinput node through udev AFTER
        ``UI_DEV_CREATE``, and events written before that are dropped with no error.

        Shared chord split with the portable backend via _parse_chord.
        """
        mods, final = _parse_chord(name)
        held = [self._key_code(m) for m in mods]
        target = self._key_code(final)
        for code, spec in zip(held, mods):
            self._check_declared(code, spec)
        self._check_declared(target, final)

        if held:
            for code in held:
                self._kbd.write(self._ecodes.EV_KEY, code, 1)
            self._kbd.syn()  # modifiers latched BEFORE the key exists
        self._kbd.write(self._ecodes.EV_KEY, target, 1)
        self._kbd.syn()
        self._kbd.write(self._ecodes.EV_KEY, target, 0)
        self._kbd.syn()  # key up while the modifiers are still down, as on real hardware
        if held:
            for code in reversed(held):
                self._kbd.write(self._ecodes.EV_KEY, code, 0)
            self._kbd.syn()

    def _char_spec(self, ch: str) -> tuple[str, bool] | None:
        """Map a character to its evdev key name + whether Shift is held (US layout).

        Covers the printable ASCII a desktop agent realistically types; unknown chars
        are skipped. Typing is inherently layout-dependent — this assumes a US keymap,
        the common case, and is enough for labels/identifiers/URLs.
        """
        named = {
            " ": ("KEY_SPACE", False), "\n": ("KEY_ENTER", False), "\t": ("KEY_TAB", False),
            "-": ("KEY_MINUS", False), "_": ("KEY_MINUS", True), "=": ("KEY_EQUAL", False),
            "+": ("KEY_EQUAL", True), ".": ("KEY_DOT", False), ",": ("KEY_COMMA", False),
            "/": ("KEY_SLASH", False), "?": ("KEY_SLASH", True), ":": ("KEY_SEMICOLON", True),
            ";": ("KEY_SEMICOLON", False), "@": ("KEY_2", True), "!": ("KEY_1", True),
        }
        if ch in named:
            return named[ch]
        if ch.isalpha() and ch.isascii():
            return (f"KEY_{ch.upper()}", ch.isupper())
        if ch.isdigit():
            return (f"KEY_{ch}", False)
        return None

    def type_text(self, text: str) -> None:
        shift = self._ecodes.KEY_LEFTSHIFT
        for ch in text:
            spec = self._char_spec(ch)
            if spec is None:
                continue
            code = getattr(self._ecodes, spec[0])
            if spec[1]:
                self._kbd.write(self._ecodes.EV_KEY, shift, 1)
            self._kbd.write(self._ecodes.EV_KEY, code, 1)
            self._kbd.write(self._ecodes.EV_KEY, code, 0)
            if spec[1]:
                self._kbd.write(self._ecodes.EV_KEY, shift, 0)
            self._kbd.syn()
            time.sleep(0.01)

    def close(self) -> None:
        self._ui.close()
        self._kbd.close()


