# Wayland uinput input injection — reach, verification, multi-monitor caveats (#79)

Researched 2026-07-29 (researcher agent, web-verified). Question: on a Wayland session does
input injected via /dev/uinput (evdev, INPUT_PROP_DIRECT absolute pointer + keyboard node)
reach native Wayland clients (GNOME/Mutter, KDE/KWin, wlroots) and XWayland clients; how to
verify device creation/consumption without xinput; multi-monitor absolute-coordinate caveats.
Closes interact issue #79 (skip xinput device check under Wayland).

## Verdicts

### A. Does injected input reach clients?

1. **Path confirmed, same for all three compositor families + XWayland.** Chain: uinput
   (`/dev/uinput` ioctl UI_DEV_CREATE) → kernel creates `/dev/input/eventN` → udev tags it →
   libinput's udev backend opens it → compositor (Mutter/KWin/wlroots, all linked against
   libinput) dispatches to whichever client holds the Wayland seat's `wl_pointer`/`wl_keyboard`
   → native Wayland clients get it directly; XWayland is itself an ordinary rootless Wayland
   CLIENT that receives forwarded events via `wl_seat` — it does NOT read evdev/libinput itself
   under a Wayland session (wlroots `wlr_xwayland` struct holds a `wl_seat` ref; wayland-book.com
   "Seats: Handling input": input chain is kernel → libevdev → libinput → compositor → Wayland
   client, XWayland is one such client).
   Source: wayland-book.com "Seats" chapter (current); wlroots `wlr/xwayland/xwayland.h` API doc
   (current, wlroots.pages.freedesktop.org).
2. **No compositor-side "tell it about the device" step needed beyond normal udev hotplug.**
   Mutter/KWin/wlroots all use libinput's udev backend, which uses a `udev_monitor` to pick up
   hotplugged devices automatically — same as plugging in real hardware. Confirmed empirically by
   ydotool (pure uinput, zero compositor-specific code), which "works with ANY Wayland compositor
   (KDE, GNOME, Sway, etc.)" because injection happens below the display server, indistinguishable
   from real hardware at the kernel/evdev level.
   Source: github.com/ReimuNotMoe/ydotool README (live 2026).
3. **libinput DOES require `ID_INPUT` + one `ID_INPUT_*` type property, else the device is
   silently ignored** — the one real gate. Set AUTOMATICALLY by systemd-udev's `input_id`
   builtin (rule `60-input-id.rules`), which classifies purely from the device's own kernel
   capability bitmasks (sysfs `capabilities/ev`, `capabilities/abs`, `capabilities/key`,
   `properties` — i.e. `EV_ABS`/`ABS_X`/`ABS_Y`/`BTN_TOUCH`/`INPUT_PROP_DIRECT`), NOT bus/vendor
   ID. Transport-agnostic: runs identically for a uinput-created device as for real hardware,
   because uinput populates the same sysfs capability attributes at `UI_DEV_CREATE`. No manual
   udev rule/hwdb entry needed for a well-formed device.
   Source: libinput "Static device configuration via udev" doc (wayland.freedesktop.org,
   unchanged wording across archived versions 1.9–1.31, current as of 2026); systemd
   `src/udev/udev-builtin-input_id.c` (github.com/systemd/systemd, `main` branch, 2026).
4. **`ID_SEAT` defaults to `seat0`** if unset — auto-assigned there like any local input device;
   no manual logind seat-assignment call needed on a single-seat desktop.
   Source: same libinput udev-config doc.
5. **Known rough edge, not a blocker**: `systemd/systemd#37063` (closed not-a-bug, 2026) shows a
   user's CUSTOM udev rule matching `ATTRS{idVendor}`/`idProduct` failing for a uinput device —
   uinput devices lack those USB attributes, so attribute-based custom rules don't match.
   Irrelevant to libinput's own capability-based auto-tagging; relevant only if interact ever
   wants a custom rule keyed on vendor/product for the virtual device (must match on
   `KERNEL=="event*"` + capability instead).
   Source: github.com/systemd/systemd/issues/37063.
6. **Verdict for #79**: injected uinput input DOES reach native Wayland clients under
   GNOME/Mutter, KDE/KWin and wlroots, AND reaches XWayland clients (forwarded via the
   compositor's own `wl_seat`, not a separate XTEST/X11 path) — provided the device exposes
   correct capability bits, which interact's existing `evdev.UInput(...,
   input_props=[INPUT_PROP_DIRECT])` construction already does. No compositor-specific
   enablement step is required. So `LocalBackend` is NOT broken on Wayland — only its
   `xinput`-based VERIFICATION was.

### B. Verifying the device without `xinput`

`xinput list` only enumerates XWayland's own X11 device list — blind to devices libinput has
claimed for the compositor, and to devices no XWayland client has yet triggered a seat
capability for. Use instead, in order of how much each proves:

1. **`sudo libinput list-devices`** — proves libinput itself claimed the device (shows kernel
   node, Seat, Capabilities, Size). Absence = the `#37063`-class udev/libinput rejection. Root
   needed per the official doc (a `uaccess`-tagged active-seat session may also work, distro/
   logind-version dependent — treat root as the safe baseline).
   Source: libinput "Helper tools" doc (current); `libinput-list-devices(1)` Arch manual page.
2. **`sudo libinput debug-events`** while injecting — proves the device is actively DELIVERING
   events into libinput (shows `DEVICE_ADDED` with seat/group, then live pointer/key events with
   coordinates/timestamps). Strongest single proof of "consumed", not just "created".
   Source: same libinput tools doc.
3. **`udevadm info /sys/class/input/eventN`** — confirms udev tagged the device: look for
   `E: ID_INPUT=1` and `E: ID_INPUT_TOUCHSCREEN=1` (or `_MOUSE`/`_KEYBOARD`). Proves the udev
   step independently of libinput; no root needed to read the properties.
   Source: udevadm(8); libinput udev-config doc worked example.
4. **`udevadm monitor -u -s input`** (add `--property` for values) run WHILE the device is
   created — shows live `ADD`/`CHANGE` uevents with properties as udev assigns them; catches
   `#37063`-class timing/attribute failures live.
   Source: udevadm(8) standard usage.
5. **`cat /proc/bus/input/devices`** — kernel's own device list, no udev/libinput involved;
   confirms the kernel-level device exists with correct `EV=`/`KEY=`/`ABS=` bitmasks and its
   `Name=`. Permission-free, but does not prove libinput consumed it.
   Source: kernel input subsystem docs (stable ABI).
6. **`cat /sys/class/input/eventN/device/name`** — same info, single value, scriptable
   (`grep -l <devname> /sys/class/input/event*/device/name`).
7. **Recommended check for interact's test/CI (replacing the `xinput` check in #79):**
   ```bash
   # 1. kernel sees it
   grep -l "interact-virtual-pointer" /sys/class/input/event*/device/name
   # 2. udev tagged it correctly
   EVENT=$(grep -l "interact-virtual-pointer" /sys/class/input/event*/device/name | sed 's#/device/name##')
   udevadm info "$EVENT" | grep -E 'ID_INPUT(_TOUCHSCREEN)?='
   # 3. libinput actually claimed it (needs root / seat access)
   sudo libinput list-devices | grep -A5 interact-virtual-pointer
   ```
   None depend on X11/XWayland — works identically under Xorg and Wayland, which is why the
   `xinput`-only check must be replaced rather than merely skipped under Wayland (#79's framing).
   Step 1 alone is root-free and deterministic, so it is the right assertion for the test suite;
   steps 2-3 are the diagnostic escalation.

### C. Multi-monitor absolute-coordinate caveats

1. **libinput itself does NOT do output placement.** Its calibration API
   (`libinput_device_config_calibration_set_matrix()`) maps the device's own coordinate range
   into a normalized 0..1 range and handles rotation/reflection; WHICH output and pixel offset is
   explicitly left to the compositor: "If the coordinate range has an offset, the compositor is
   responsible for applying that offset after the mapping."
   Source: libinput "Absolute axes" doc (wayland.freedesktop.org, current).
2. **KWin**: explicit per-output touch mapping since patch D8748 (authored 2017-11-10, landed
   2017-12-24) — picks the output via heuristic (screen count, an output-name tag on the device,
   "is it internal", physical size) and applies calibration relative to that output. Patch's own
   note: **"This only affects libinput on Wayland and not on X11!"**
   Source: phabricator.kde.org/D8748 (2017; not re-diffed against latest KWin in this pass —
   flag as possibly extended since, mechanism still current per shipped KWin architecture).
3. **GNOME/Mutter**: auto-maps touchscreen→monitor by heuristic (vendor/product ID match,
   matching dimensions, "is one monitor internal") — MISFIRES for a generic/virtual device with
   no matching monitor EDID (typical for an injected uinput device), commonly binding to the
   wrong (e.g. first/internal) monitor. No GNOME Settings UI override; must set via a
   relocatable gsettings schema keyed by the touch device's own USB vendor/product/serial:
   ```
   gsettings set org.gnome.desktop.peripherals.touchscreen:/org/gnome/desktop/peripherals/touchscreens/<DEVICE_ID>/ output "['<MON_VENDOR>','<MON_PRODUCT>','<MON_SERIAL>']"
   ```
   A virtual uinput device has no real USB vendor/product ID (evdev lets you set arbitrary
   `vendor`/`product`/`bustype` in `uinput_setup`) — pick stable fake IDs to keep this scriptable
   if interact ever needs to pin virtual touch to one output on a multi-monitor host.
   Source: Peter Hutterer (libinput maintainer), "Enforcing a touchscreen mapping in GNOME",
   who-t.blogspot.com, dated 2024-03-12.
4. **Practical implication for interact**: on a single-output target (one physical screen, or
   one nested/virtual display — interact's common case) this class of bug cannot trigger — only
   one output exists to map to. Relevant only for a real multi-monitor host with touch injection
   scoped to one screen. Interact's `target="screen:<index>"` already computes a region origin
   for coordinate mapping at the interact level (`desktop/coords.py`), a DIFFERENT mechanism from
   compositor-side touch-output mapping — not currently known to conflict, but not empirically
   cross-checked against a real multi-monitor GNOME/KDE host in this research pass.

## Practical takeaway for #79

Drop the `xinput`-based device check for Wayland sessions — confirmed correct: `xinput` cannot
see compositor/libinput-claimed devices (it only ever saw XWayland's own list). Replace with the
kernel-level `/sys/class/input/*/device/name` assertion in B.7 step 1, which is root-free and
display-server-agnostic. The injection path itself (A) is not Wayland-specific-broken: it works
identically across GNOME/KDE/wlroots and XWayland once the device's capability bits are correct,
which interact's existing `INPUT_PROP_DIRECT` + `ABS_X`/`ABS_Y` touchscreen device already
satisfies.
