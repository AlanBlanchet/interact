# Touch input for the isolated sandbox (Flutter drag gap, #38/#39)

Researched 2026-07-07 (researcher agent, web-verified). Question: how can the agent sandbox
inject TOUCH so Flutter drag gestures (DraggableScrollableSheet, kinetic drags) work — given
Flutter's `ScrollBehavior.dragDevices` excludes mouse?

## Verdicts

1. **Xephyr / XTEST touch: impossible, architecturally.** XTEST has only
   FakeKey/FakeButton/FakeMotion — no touch request exists in any released libXtst (a 2017
   xorg-devel "Virtual Touch Events for XTEST" proposal never shipped). Xephyr has no
   evdev/seat input path; it relays core events from its host window. No flag fixes this.
   Source: X.org XTEST spec; xorg-devel Feb 2017 thread; Xephyr(1).

2. **wlroots (sway/cage/labwc): no virtual-TOUCH protocol at all** — only
   `zwlr_virtual_pointer_v1` + `zwp_virtual_keyboard_v1`. **Weston**: `weston-test.send_touch`
   exists but the module is explicitly test-suite-only ("should never be installed").
   **mutter --headless**: libei-backed RemoteDesktop D-Bus exists, but consent-free headless
   driving is UNVERIFIED (no shipped tool demonstrates it). **KWin `kwin_wayland --virtual`:
   CONFIRMED, shipped path** — KWin's own `org.kde.KWin.EIS.RemoteDesktop` D-Bus hands back a
   libei fd, no portal consent dialog; proven by `isac322/kwin-mcp` (MIT, v0.7.0 2026-03-29,
   multi-touch tap/swipe/pinch, runs headless under `dbus-run-session`, software rendering,
   needs Plasma 6.x). Python client stack for raw libei: **snegg** (official bindings by the
   libei author; ei_touch_down/move/up).

3. **Flutter + touch needs no XWayland**: the Linux GTK embedder has a native touch path
   (`fl_touch_manager.cc` consuming GdkEventTouch → PointerDeviceKind.touch). GDK picks the
   native Wayland backend when `WAYLAND_DISPLAY` is set — run the app native-Wayland under the
   virtual KWin session and real touch reaches DraggableScrollableSheet.

4. **uinput multitouch (type B) touchscreen**: works with zero Xorg config on the REAL session
   (udev input_id auto-tags via BTN_TOUCH + ABS_MT_* + INPUT_PROP_DIRECT; libinput autodetects;
   map-to-output only matters with >1 output). But it's REAL-SESSION only — Xephyr has no
   device stack, so this does NOT help the isolated sandbox. Valid as a non-isolated
   LocalBackend primitive.

## Recommended architecture

Isolated sandbox with touch = **`kwin_wayland --virtual` + libei/EIS injection** (mirror
kwin-mcp's design: KWin's EIS D-Bus → libei fd; capture via KWin-native tooling). Cost: a new
backend family with a hard KDE Plasma 6 dependency — interact is otherwise DE-agnostic.
Non-KDE alternative (mutter) needs its own prototype+verify pass first.

## Cheapest interim workaround (no new compositor)

The Flutter gap is `dragDevices` excluding MOUSE, not missing touch per se: when we control
the driven app's source, a one-line `ScrollBehavior` override adding `PointerDeviceKind.mouse`
to `dragDevices` (agent/test build only) makes the existing Xephyr sandbox's mouse drags work.
Documented on #38/#39; only applies to apps whose source the user owns.
