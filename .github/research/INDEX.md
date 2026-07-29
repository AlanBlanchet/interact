# Research store

- touch-input-nested-sandbox — KWin/libei EIS = only proven touch-injection path for an isolated Wayland sandbox; Xephyr/XTEST has no touch, wlroots has no touch protocol; interim = app-side dragDevices override — 2026-07-07 — verified
- dev-tool-landing-pages — AI-agent/browser-automation landing-page + branding survey (8 tools) for interact's GH Pages showcase — 2026-07-12 — verified
- wayland-uinput-injection — uinput injection DOES reach Wayland + XWayland clients on all 3 compositor families (libinput auto-tags via capability bits, no seat step); verify with /sys/class/input + libinput list-devices, never xinput; multi-monitor touch mapping is compositor-side — 2026-07-29 — verified
