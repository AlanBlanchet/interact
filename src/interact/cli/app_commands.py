"""Deferred command implementations for the lightweight root CLI."""

import asyncio
import os
import platform as _pf
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

from interact import feedback, live_sources, ollama
from interact.agents import messaging
from interact.agents import registry as reg
from interact.agents.host import run_console
from interact.agents.policy import Policy, policy_path
from interact.agents.providers import (
    MEDIA_PROVIDERS,
    PROVIDERS,
    available_providers,
    provider_for,
)
from interact.agents.run import ModelUnavailable, is_criterion, resolve_model, run_agent
from interact.cli.clients import ClientTarget, MCPServer, Scope
from interact.cli.command_bootstrap import Config, UserConfig
from interact.cli.render import CliRenderer
from interact.cli.update import REPO, available_update, installed_version
from interact.cli.usage import UsageReport, default_log_path
from interact.cli.view import View
from interact.criteria import Variables
from interact.desktop import backend as desktop_backend
from interact.desktop import orphans
from interact.extension_status import deliver_extension, extension_status
from interact.models import Model, ModelCapability
from interact.runtime import _LiveConfig, config
from interact.server_registry import kill_stale_servers, latest_version, stale_servers


def _print_media_transport(config: Config | _LiveConfig, indent: str = "  ") -> None:
    """Print the configured visual transport and registry-backed subscription CLI readiness."""
    order = tuple(config.media_provider_order)
    print(
        f"{indent}media        : backend={config.media_backend} "
        f"billing={config.media_billing}  order={' → '.join(order) or 'none'}"
    )
    confirmed = set(config.media_session_no_extra_usage_confirmed_for)
    for name in order:
        provider = MEDIA_PROVIDERS[name]
        availability = (
            "installed — subscription login is verified when a visual request runs"
            if provider.available()
            else f"not installed — install and log in with the {provider.binary} CLI"
        )
        confirmation = (
            "no-extra-usage confirmed (account state remains unverifiable)"
            if name in confirmed
            else (
                f"SESSION BLOCKED for this provider — {provider.no_extra_usage_guidance}; "
                f"then add {name} to media.noExtraUsageConfirmedFor"
            )
        )
        print(f"{indent}  · {name:<10} {availability}; {confirmation}")
    if config.media_billing == "session_only":
        print(
            f"{indent}  no metered API fallback by interact; vendor session credit controls "
            "remain account-side; audio is disabled until media.billing=api_allowed"
        )
    elif config.media_backend == "session":
        print(
            f"{indent}  visual work stays on sessions; audio may use its configured API/local "
            "backend"
        )
    else:
        print(f"{indent}  metered API use is explicitly allowed")


def _print_resolved_models(indent: str = "  ") -> None:
    """Print which model each VLM TASK resolves to with the current keys — the answer to "what runs
    when I do X, and why that default?". Organised BY TASK (what a user actually picks) with the
    config knob (the role) named in brackets, so it's clear different jobs can have different defaults
    — without a separate model setting per task (they'd all resolve to the same best VLM). The real
    axes are MODALITY (image/component/video/audio) and STAKES: review_ui/verify_ui layer a quality
    tier on the image model — a cheap private sovereign GLM at low/medium, the frontier image model at
    high/critical. Shared by status / providers / doctor / version so every surface tells one story."""

    Model.load_registry()

    def _resolved(role: str) -> tuple[str, str]:
        """(display string, bare model id) for a role given the current keys."""
        pinned = getattr(config, f"{role}_model", "")
        try:
            mid = config.resolve_model(role)
        except RuntimeError:
            mid = ""
        ok = bool(mid) and Model.from_litellm_id(mid).is_available()
        flag = "" if ok else "  ⚠ key missing — add it or pin a model"
        return f"{mid or '—'} ({'pinned' if pinned else 'auto'}){flag}", mid

    def _line(task: str, role: str) -> None:
        print(f"{indent}{task:<33}→ {_resolved(role)[0]}  [{role}]")
        # What it stepped over. "Are we using the best model?" is unanswerable from the chosen id
        # alone — that reads identically whether the walk found the strongest available or a stale
        # default was returned with no walk at all. Naming the stronger models it could not reach,
        # and why, is what makes the answer checkable — and shows which key to add to get more.
        for passed in config.explain_model(role).skipped:
            print(f"{indent}{'':<33}  ↑ {passed.model} — {passed.reason}")

    _line("screenshot(query) · describe", "image")
    _line("get_interactive_elements", "component")
    _line("transcribe", "audio")
    _line("record · video understanding", "video")

    # review_ui / verify_ui pick by STAKES, not role: a cheap private sovereign GLM for a quick look
    # (low/medium), the frontier image model for a final sign-off (high/critical).
    frontier = _resolved("image")[1] or "—"
    sovereign = config.resolve_quality_model("low")
    if sovereign:
        critique = f"{sovereign} (low/medium tier) · {frontier} (high/critical)"
    else:
        critique = f"{frontier} (all tiers — no z.ai/Novita key, so low/medium fall back to frontier)"
    print(f"{indent}{'review_ui · verify_ui (critique)':<33}→ {critique}")
    print(f"{indent}{'measure_ui (contrast)':<33}→ deterministic — no model")


#: Enough to see the shortlist without burying the rest of `doctor` — a cloud catalog is ~19 rows.
_OLLAMA_SHOWN = 8


def _print_ollama(indent: str = "  ") -> None:
    """Name what the Ollama daemon actually serves, so "did interact see the model I pulled?" is
    answerable without guessing.

    Vision models are named individually because those are the ones interact can DRIVE; the rest
    are counted, not listed, because a wall of text-only ids would bury the rest of doctor without
    telling him anything he can act on. Silent when there is no daemon — someone who does not run
    Ollama must not read a line about it.
    """

    found = ollama.serving()
    if not found:
        return
    # Where they CAME from, not where we looked first — discovery walks a ladder, and this is
    # also the endpoint a completion will be sent to, so the two are checkable against each other.
    where = found[0].base or ollama.candidate_bases()[0]
    vision = sorted((m for m in found if m.vision), key=lambda m: m.name)
    rest = sorted((m for m in found if not m.vision), key=lambda m: m.name)

    usable = f"{len(vision)} vision-capable" if vision else "none vision-capable"
    print(f"{indent}{'ollama':<14}: {len(found)} available on {where} — {usable}")
    for model in vision[:_OLLAMA_SHOWN]:
        print(f"{indent}  · {model.describe()}")
    if len(vision) > _OLLAMA_SHOWN:
        print(f"{indent}  · … +{len(vision) - _OLLAMA_SHOWN} more vision models")
    if rest:
        names = ", ".join(m.name for m in rest[:_OLLAMA_SHOWN])
        more = f", +{len(rest) - _OLLAMA_SHOWN} more" if len(rest) > _OLLAMA_SHOWN else ""
        print(f"{indent}  · text-only ({len(rest)}): {names}{more}")


def _print_stale_servers(indent: str = "  ", fix: bool = False) -> None:
    """Flag any RUNNING MCP server that loaded an OLDER version than is now available — the silent
    stale-server trap (a long-lived `interact mcp` keeps serving the code it imported at startup, so
    a shipped fix never reaches it until reconnected). Names the pid so the user knows which editor
    window's interact MCP server to reconnect. With ``fix=True`` (``interact doctor --fix``) it
    restarts them itself (SIGTERM → the editor respawns interact on current code). Nothing printed
    when every server is current."""

    stale = stale_servers()
    if not stale:
        return
    latest = latest_version()
    if fix:

        killed = kill_stale_servers()
        if killed:
            pids = ", ".join(str(p) for p in killed)
            print(f"{indent}✓ restarted {len(killed)} stale MCP server(s) (pid {pids}) — each editor "
                  f"respawns interact on current code (v{latest}) on its next tool call.")
        else:
            print(f"{indent}⚠ stale server(s) found but none could be restarted (not interact mcp, or "
                  f"no permission) — reconnect them from your editor.")
        return
    print(f"{indent}⚠ stale MCP server(s) — serving code older than this tree; reconnect to load fixes")
    print(f"{indent}   (or run `interact doctor --fix` to restart them):")
    for s in stale:
        if s.get("reason") == "code":
            # The common case between releases: the version never moved, the code did.
            print(f"{indent}    pid {s['pid']}: v{s.get('version')} — started before the last edit")
        else:
            print(f"{indent}    pid {s['pid']}: v{s.get('version')} (tree is v{latest})")


def _print_extension_status(indent: str = "  ", fix: bool = False) -> None:
    """Flag a VS Code extension the user is running that is not the one in this tree.

    A version or compiled-bundle mismatch needs installation. A current bundle loaded before its
    build needs only a restart. These remedies are intentionally distinct: neither operation can
    substitute for the other, and nothing is printed when the running editor has this build.
    """

    st = extension_status()
    if not st:
        return
    if st["remedy"] == "install":
        if st["reason"] == "version":
            print(
                f"{indent}⚠ VS Code extension v{st['installed']} installed, "
                f"tree is v{st['tree']} — repackage and reinstall to load fixes"
            )
        else:
            print(
                f"{indent}⚠ VS Code extension v{st['installed']} compiled bundle differs from "
                "this tree — repackage and reinstall before restarting"
            )
        if fix:
            # Pair the detection with the remedy. Only on an explicit --fix: installing an
            # extension makes VS Code reload its extension hosts, which kills whatever session
            # asked for it — including, often, the one running this command.

            print(f"{indent}   packaging and installing v{st['tree']}…")
            if deliver_extension():
                print(f"{indent}   ✓ installed v{st['tree']}. FULLY CLOSE AND REOPEN a window — a "
                      "reload is served by the same extension host and will not pick it up.")
            else:
                print(f"{indent}   could not deliver it; the messages above say why.")
    else:
        n, total = st.get("behind", 1), st.get("running", 1)
        print(f"{indent}⚠ VS Code extension v{st['installed']} was rebuilt after {n} of {total} "
              "running editor process(es) started — those are serving the OLD build")
        print(f"{indent}   a reinstall at the same version does NOT reach a running window; "
              "fully restart it (or use a fresh --user-data-dir)")


def _print_sandboxes(real_display: str | None) -> None:
    """Which sandbox displays exist right now, and who owns each.

    Answers "why do I see two Xephyr windows?" — every interact server owns its own sandbox, so
    one window per server that has launched something is BY DESIGN. What is not by design is a
    window whose owner is gone, which is called out here and swept on the next launch.
    """

    try:
        servers = orphans._list_x_servers()
    except (OSError, subprocess.SubprocessError):
        return
    if not servers:
        return
    print(f"  sandboxes     : {len(servers)} open (one per interact server that has launched an app)")
    for srv in servers:
        where = orphans.display_of(srv.cmdline) or "?"
        clients = len(orphans.display_clients(where)) if where != real_display else 0
        owner = "ORPHANED — no owner left; swept on the next launch" if orphans.is_orphan(srv) \
            else f"owner pid {srv.ppid}"
        print(f"                  {where}  {clients} app(s)  ({owner})")


def status(
    project: Annotated[Path, Parameter(name=["--project", "-p"])] = Path("."),
) -> None:
    """Show how interact is set up: which clients it's registered with, the configured
    subscription-media policy, models and desktop target, optional API keys, and recent usage. The
    at-a-glance overview for a normal user (grounding/scenario probes live in the tests).

    Parameters
    ----------
    project
        Project root to check for project-scoped client registrations (default: cwd).
    """

    root = project.resolve()
    print("interact status\n")
    _print_stale_servers()

    print("Registered with (interact install <client> to add):")
    bound = False
    for target in ClientTarget.all():
        registrations = target.registrations(root)
        if registrations:
            bound = True
            print(f"  ✓ {target.label}: {', '.join(registrations)}")
    if not bound:
        print("  (none yet)")

    print("\nMedia analysis:")
    _print_media_transport(config)

    print("\nModels (API/local roles and fallback models — pin via `interact config set`):")
    _print_resolved_models()
    if config.media_billing == "session_only":
        print("  note       API/local role models are inactive while media.billing=session_only")

    if not desktop_backend.desktop_supported():
        print("  desktop    not available on this OS (Linux/X11 only) — browser automation works here")
    else:
        target_line = f"target={config.desktop_target}"
        if config.desktop_target == "nested":
            target_line += f"  headless={config.nested_headless}  display=:{config.nested_display}"
        print(f"  desktop    {target_line}")

    Model.load_registry()
    providers = Model.available_providers()
    grounding = Model.available_by_capability(ModelCapability.GUI_GROUNDING)
    print(
        f"\nAPI keys (optional for visual subscriptions; required by configured audio/API paths): "
        f"{', '.join(providers) or 'none'}"
    )
    print(f"Grounding models ready: {len(grounding)}")

    report = UsageReport.build(since_days=30)
    session_note = (
        f"; {report.session_usage_calls} session-usage call(s), account impact unknown"
        if report.session_usage_calls
        else ""
    )
    print(
        f"\nUsage (last 30d): {report.entries} calls, observed metered API spend "
        f"${report.total_cost:.4f}{session_note}   (details: interact usage)"
    )


def install(
    client: str | None = None,
    *,
    scope: Scope = Scope.user,
    project: Path = Path("."),
    dev_from: Path | None = None,
    dry_run: bool = False,
) -> None:
    """Register the interact MCP server with a coding client.

    Parameters
    ----------
    client
        Client id (omit to list them): claude, cursor, codex, vscode, copilot, windsurf, zed, claude-desktop.
    scope
        ``user`` (default) or ``project`` config location.
    project
        Project root for ``--scope project`` (default: current directory).
    dev_from
        Run the server from a local checkout via ``uvx --from <path> interact mcp``.
    dry_run
        Print what would be written/run without changing anything.
    """
    if client is None:
        print("Known clients (use: interact install <client>):\n")
        for target in ClientTarget.all():
            scopes = [s.value for s in Scope if target.path_for(s, Path(".")) is not None]
            print(f"  {target.id:<16} {target.label:<24} scopes: {', '.join(scopes) or 'cli'}")
            if target.note:
                print(f"  {'':<16} {target.note}")
        print("\n  (copilot is an alias of vscode)")
        return

    target = ClientTarget.by_id(client)
    if target is None:
        print(f"Unknown client '{client}'. Known: {', '.join(ClientTarget.ids())}")
        raise SystemExit(2)

    root = project.resolve()
    server = MCPServer.resolve(
        dev_from=dev_from,
        portable=scope == Scope.project,
        project=root,
    )
    result = target.install(server, scope, root, dry_run)
    icon = {"wrote": "✓ wrote", "ran": "✓ ran", "manual": "→ manual", "skipped": "• skipped"}[result.action]
    print(f"{icon}: {target.label}  [{result.target}]")
    if result.detail:
        print(result.detail)
    print(f"\nLaunches: {server.command} {' '.join(server.args)}")
    print(f"Docs: {target.doc_url}")
    if target.note and result.action in ("wrote", "ran"):
        print(f"Note: {target.note}")
    if target.id == "codex" and result.action in ("wrote", "ran", "skipped"):
        print("Start a fresh Codex session, or restart the Codex IDE extension, then verify:")
        print("  codex mcp get interact")


def providers() -> None:
    """List subscription CLIs plus API/local providers and grounding models."""

    Model.load_registry()
    available = Model.available_providers()
    print("Subscription visual providers:")
    _print_media_transport(Config())
    print(
        f"\nAPI/local providers ({len(available)}): "
        f"{', '.join(available) or 'none (subscription visual sessions can still run)'}"
    )

    print("\nResolved selection (what each tool uses, given your keys):")
    _print_resolved_models()

    grounding = Model.available_by_capability(ModelCapability.GUI_GROUNDING)
    print(f"\nGrounding models ready ({len(grounding)}):")
    for model in grounding:
        print(f"  {model.id:<40} ${model.cost_score:.2f}/Mtok")


def dashboard() -> None:
    """Show the status dashboard (providers, models, grounding) in the terminal.

    Renders the same declarative `View` an HTTP endpoint will serve to the browser
    and the VS Code webview — defined once, shown on every surface. No VLM calls.
    """

    CliRenderer.render(View.dashboard(config))


def usage(
    days: Annotated[int | None, Parameter(name=["--days", "-d"])] = None,
) -> None:
    """Summarise local VLM spend, tokens and calls by model and provider.

    Reads ~/.interact/out/usage.jsonl (the same log the VS Code dashboard charts) —
    no network, no API calls. This is the CLI's usage analysis.

    Parameters
    ----------
    days
        Only count calls from the last N days (default: all time).
    """

    log_path = default_log_path()
    report = UsageReport.build(since_days=days)
    window = f"last {days}d" if days else "all time"
    if report.entries == 0:
        where = "no calls recorded yet" if not log_path.exists() else f"no calls in the {window}"
        print(f"interact usage ({window}): {where}\n  log: {log_path}")
        return

    unknown = (
        f"; {report.session_usage_calls} session-usage call(s) with unknown account impact"
        if report.session_usage_calls
        else ""
    )
    print(
        f"interact usage ({window}) — {report.entries} calls, observed metered API spend "
        f"${report.total_cost:.4f}{unknown}, {report.total_input:,} in / "
        f"{report.total_output:,} out tokens\n"
    )
    print(f"  {'model':<40} {'calls':>6} {'in':>10} {'out':>10} {'cost':>10}")
    for group in report.by_model:
        cost = (
            f"${group.cost:.4f} + unknown"
            if group.unknown_cost_calls and group.cost
            else "unknown"
            if group.unknown_cost_calls
            else f"${group.cost:.4f}"
        )
        print(
            f"  {group.name:<40} {group.calls:>6} {group.input_tokens:>10,} "
            f"{group.output_tokens:>10,} {cost:>10}"
        )
    if len(report.by_provider) > 1:
        print("\n  by provider:")
        for group in report.by_provider:
            cost = (
                f"${group.cost:.4f} + unknown"
                if group.unknown_cost_calls and group.cost
                else "unknown"
                if group.unknown_cost_calls
                else f"${group.cost:.4f}"
            )
            print(f"  {group.name:<40} {group.calls:>6} {' ':>10} {' ':>10} {cost:>10}")


def update(check: Annotated[bool, Parameter(name=["--check", "-c"])] = False) -> None:
    """Update interact to the latest GitHub release (or just check with --check).

    Parameters
    ----------
    check
        Only report whether an update is available; don't install it.
    """


    current = installed_version()
    newer = available_update()
    if not newer:
        print(f"interact {current} is up to date.")
        return
    print(f"Update available: {current} → {newer}")
    if check:
        print("Run `interact update` to install it.")
        return
    source = f"git+https://github.com/{REPO}"
    if shutil.which("uv"):
        subprocess.run(["uv", "tool", "install", "--force", source], check=True)
    elif shutil.which("pipx"):
        subprocess.run(["pipx", "install", "--force", source], check=True)
    else:
        print("Need uv or pipx to update. See install.sh.")
        raise SystemExit(1)
    print(f"✓ updated to {newer}")


def report(
    title: str,
    body: str,
    kind: Annotated[str, Parameter(name=["--kind", "-k"])] = "bug",
) -> None:
    """Report a problem or idea about interact itself to its maintainers (GitHub issue).

    The shell twin of the MCP ``report_issue`` tool — any agent or user with a terminal can
    send feedback without an MCP connection: ``interact report "title" "what happened"``.

    Parameters
    ----------
    title
        One-line summary of the problem or request.
    body
        What happened, what you expected, any repro steps or environment details.
    kind
        bug | limitation | feedback.
    """

    print(feedback.report(title, body, kind))


def doctor(*, fix: bool = False) -> None:
    """Diagnose the environment: command, providers, Playwright, desktop capture.

    Parameters
    ----------
    fix
        Deliver this tree to what you are actually running: restart any stale `interact mcp`
        server (it respawns on current code from your editor), and repackage + reinstall the VS
        Code extension when the installed one is older than this tree. The one-step cure for "I
        shipped the fix but the bug persists" — which is a real failure mode here, not a slogan:
        a day's work once sat undelivered behind a warning this command could only print.

        Installing an extension makes VS Code reload its extension hosts, so expect this to
        interrupt sessions in your editor windows — which is why it never happens without --fix.
    """


    print("interact doctor\n")
    _print_stale_servers(fix=fix)
    _print_extension_status(fix=fix)
    print(f"  command       : {shutil.which('interact') or 'NOT on PATH'}")
    print(f"  config file   : {UserConfig.PATH} ({'present' if UserConfig.PATH.exists() else 'absent'})")

    if find_spec("playwright") is not None:
        print(f"  playwright    : installed (browser: {os.environ.get('INTERACT_BROWSER_TYPE', 'chromium')})")
    else:
        print("  playwright    : MISSING — run `uv run playwright install`")


    _print_media_transport(config)

    # Desktop diagnostics are Linux/X11-specific (maim, /dev/uinput, Xephyr). On macOS/Windows
    # they'd print misleading "MISSING (apt install …)" / "udev rule" advice, so report cleanly
    # that desktop automation is N/A here and browser automation is the ready path.
    if not desktop_backend.desktop_supported():

        print(f"  desktop       : not available on {_pf.system()} — desktop automation is "
              "Linux/X11 only (issues/24); browser automation works fully here.")
    else:
        session = os.environ.get("XDG_SESSION_TYPE", "?")
        display = os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")
        maim = shutil.which("maim")
        print(f"  desktop       : session={session} display={display or 'none'} maim={maim or 'MISSING (apt install maim)'}")
        _print_sandboxes(display)
        if session == "wayland":
            print("                  note: browser + the nested sandbox + uinput input work on "
                  "Wayland; local (non-nested) window capture/enumeration is X11-only for now "
                  "→ prefer `desktop.target=nested`.")
        print(f"  desktop target: {config.desktop_target}  (set: interact config set desktop.target local|nested)")
        if config.desktop_target == "nested":
            server = "Xvfb" if config.nested_headless else "Xephyr"
            pkg = "xvfb" if config.nested_headless else "xserver-xephyr"
            server_path = shutil.which(server) or f"MISSING (apt install {pkg})"
            xdotool = shutil.which("xdotool") or "MISSING (apt install xdotool)"
            mode = "headless/background" if config.nested_headless else "visible"
            print(f"  nested deps   : {server}={server_path} ({mode}) xdotool={xdotool} display=:{config.nested_display}")
        uinput = "writable" if os.access("/dev/uinput", os.W_OK) else "NOT writable — add a udev rule + join `input` group (no root)"
        print(f"  input driver  : /dev/uinput {uinput}  (absolute pointer, works on X11 + Wayland)")

    Model.load_registry()
    available = Model.available_providers()
    grounding = Model.available_by_capability(ModelCapability.GUI_GROUNDING)
    print(
        f"  API/local     : {', '.join(available) or 'none (subscription visuals need no API key)'}"
    )
    print(f"  grounding     : {len(grounding)} model(s) ready")
    _print_ollama()
    print("  selection     : (what each tool resolves to — answers 'why is my default X?')")
    _print_resolved_models(indent="    ")


config_app = App(name="config", help="Persist model/key settings to ~/.interact/config.env.")


def _mask(name: str, value: str) -> str:
    return f"{value[:4]}…{value[-4:]}" if name.endswith("_API_KEY") and len(value) > 8 else value


@config_app.command(name="list")
def config_list() -> None:
    """Show persisted settings (secrets masked)."""
    data = UserConfig.read()
    if not data:
        print(f"No settings yet. Set one with: interact config set image.model <id>\n({UserConfig.PATH})")
        return
    for name, value in sorted(data.items()):
        print(f"  {name} = {_mask(name, value)}")


@config_app.command(name="get")
def config_get(key: str) -> None:
    """Print one persisted value."""
    value = UserConfig.get(key)
    print(value if value is not None else f"{UserConfig.normalize_key(key)} is unset")


@config_app.command(name="set")
def config_set(key: str, value: str) -> None:
    """Persist a setting. e.g. `interact config set image.model gpt-4o` or `... OPENAI_API_KEY sk-...`."""
    env = UserConfig.set(key, value)
    print(f"✓ {env} = {_mask(env, value)}  →  {UserConfig.PATH}")


@config_app.command(name="unset")
def config_unset(key: str) -> None:
    """Remove a persisted setting."""
    env = UserConfig.normalize_key(key)
    print(f"✓ removed {env}" if UserConfig.unset(key) else f"{env} was not set")


@config_app.command(name="path")
def config_path() -> None:
    """Print the config file path."""
    print(UserConfig.PATH)


agents_app = App(name="agents", help="Spawn and supervise agent runs across providers.")


@agents_app.command(name="console")
def agents_console(workspace_root: Path) -> None:
    """Run the extension's private newline-JSON conversation console on standard I/O."""

    run_console(workspace_root)


@agents_app.command(name="list")
def agents_list(foreign: bool = True) -> None:
    """Show agent runs: status, what each is doing, and API-equivalent cost.

    Parameters
    ----------
    foreign
        Also show agent sessions interact did not start (your own editor windows).
    """

    runs = reg.list_runs(include_foreign=foreign)
    if not runs:

        names = ", ".join(p.name for p in available_providers()) or "none installed"
        print(f"No agent runs. Providers available here: {names}.")
        return
    for run in runs:
        cost = f"~${run.cost_usd:.4f}" if run.cost_usd is not None else "—"
        mark = "*" if run.foreign else " "
        print(f"{mark} {run.status:8} {run.run_id[:8]}  {run.provider:7} {run.name:16} "
              f"{cost:>10}  {run.last[:60]}")
    if any(r.foreign for r in runs):
        print("\n* not started by interact")


@agents_app.command(name="events")
def agents_events(run_id: str, limit: int = 30) -> None:
    """Print what an agent run has been doing. Takes the short id `agents list` prints."""

    resolved = reg.resolve_run_id(run_id) or run_id
    events = reg.read_events(resolved)
    if not events:
        print(f"No events for {run_id!r}.")
        return
    for event in events[-max(1, limit):]:
        print(f"  {event.kind:11} {event.summary(viewer=resolved)}")


@agents_app.command(name="stop")
def agents_stop(run_id: str) -> None:
    """Stop a running agent and the tools it spawned. Takes the short id `agents list` prints."""

    resolved = reg.resolve_run_id(run_id)
    if resolved is None:
        print(f"No agent run {run_id!r}.")
        return
    print(f"Stopped {resolved[:8]}." if reg.stop(resolved) else f"No agent run {run_id!r}.")


def refresh_live_data() -> None:
    """Re-fetch the live model catalog and benchmark scores the dashboard reads.

    Python is the SOLE writer of those cache files — the extension used to fetch and write the
    catalog itself with a narrower schema, so whichever side wrote last decided whether prices
    existed. Now the extension asks for this instead.
    """

    done = live_sources.refresh_all()
    print("Refreshed: " + ", ".join(done) if done else "Nothing refreshed (offline, or no API key).")


@agents_app.command(name="send")
def agents_send(run_id: str, message: str) -> None:
    """Send a message to a running agent — it answers with its full context intact.

    This is how the VS Code panel lets you join the conversation instead of only watching it: the
    agent resumes its own session, so it remembers what it has already done and its reply lands in
    the same transcript the panel shows.
    """


    run, error = messaging.check_deliverable(run_id)
    if error:
        print(error)
        return
    assert run is not None
    run_id = run.run_id  # deliver against the full id, whatever prefix was typed
    if error := messaging.record_exchange(messaging.sender_id(), run_id, message):
        print(error)
        return
    argv = provider_for(run.provider).resume_command(run_id, message)
    with reg.open_raw_events(run_id, append=True) as sink:
        try:
            subprocess.Popen(argv, cwd=run.cwd or ".", stdout=sink,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            print(f"ERROR: could not deliver to {run.name} — {e}")
            return
    print(f"Delivered to {run.name} ({run_id[:8]}). It is answering now.")


@agents_app.command(name="variables")
def agents_variables() -> None:
    """Every comparison a model criterion can make, and who measured each one.

    The discovery surface for writing a criterion: you cannot write ``aa.mmmu > 0.7`` if nothing
    tells you it exists. Each variable is namespaced by its SOURCE — a bare ``intelligence``
    hides who measured it, and two leaderboards rarely agree.
    """

    rows = Variables.all()
    width = max(len(v.name) for v in rows)
    for v in sorted(rows, key=lambda v: v.name):
        kind = "yes/no  " if v.flag else "measure "
        print(f"  {v.name:<{width}}  {kind} {v.describe}")
    print("\nWrite one as  cap.vlm and gui.screenspot > 0.85 and price.in < 10  — cheapest that"
          " clears every term is used, and re-resolved at every spawn.")


@agents_app.command(name="policy")
def agents_policy() -> None:
    """What ~/.interact/agents.json says: profiles, who wears them, toolsets, providers.

    Each agent row shows the rule as WRITTEN and what it currently RESOLVES to, so a criterion
    that quietly matches nothing is visible here rather than at the spawn that fails.
    """


    policy = Policy.load()
    print(f"policy: {policy_path()}")
    if policy.profiles:
        print("\nprofiles")
        for name, rule in policy.profiles.items():
            print(f"  @{name:<14} {rule}")
    if policy.agents:
        print("\nagents")
        for agent, rule in policy.agents.items():
            resolved = policy.criterion_for(agent) or ""
            shown = rule if rule == resolved else f"{rule}  →  {resolved}"
            note = ""
            if is_criterion(resolved):
                # What each switched-on vendor CLI would ACTUALLY run — resolved by the code the
                # spawn uses, per CLI, because the pool is what that binary can be pointed at; a
                # catalog-wide answer here once named a model the claude spawn could never run.
                answers = []
                for pname in PROVIDERS:
                    if not policy.provider_active(pname):
                        continue
                    try:
                        _, chosen = resolve_model(resolved, dict(os.environ), provider=provider_for(pname))
                        answers.append(f"{pname} ⇒ {chosen}")
                    except ModelUnavailable as err:
                        answers.append(f"{pname} ⇒ NOTHING ({str(err).splitlines()[0].rstrip(':')})")
                note = "  " + "; ".join(answers) if answers else "  ⇒ every provider is switched off"
            print(f"  {agent:<16} {shown}{note}")
    if policy.toolsets:
        print("\ntoolsets")
        for name in policy.toolsets:
            print(f"  @{name:<14} {', '.join(policy.expand_toolset(name))}")
    if policy.agent_tools:
        print("\nagent tools")
        for agent in policy.agent_tools:
            print(f"  {agent:<16} {', '.join(policy.tools_for(agent))}")
    print("\nproviders")
    for name in PROVIDERS:
        print(f"  {name:<8} {'on' if policy.provider_active(name) else 'off'}")


@agents_app.command(name="clear")
def agents_clear(run_id: str | None = None) -> None:
    """Forget finished agent runs — all of them, or one by the short id `agents list` prints.

    A running agent is never forgotten: its record is the only handle on the process.
    """

    if run_id:
        print(f"Forgot {run_id}." if reg.forget(run_id)
              else f"Kept {run_id!r} — unknown, or still running.")
        return
    cleared = reg.clear_finished()
    print(f"Forgot {len(cleared)} finished run(s)." if cleared else "Nothing finished to clear.")


@agents_app.command(name="providers")
def agents_providers(name: str | None = None, state: str | None = None) -> None:
    """Which agent CLIs drive agents here — list them, or switch one on/off.

    ``interact agents providers`` lists each provider as ``<name> <on|off> <availability>``, then
    the named agents and permission modes it can resolve. ``interact agents providers codex off``
    switches one off at the one place every spawn passes through (``~/.interact/agents.json``),
    so the panel's toggle and this command read and write the same fact. Unmentioned providers
    are ON: a CLI you installed is one you meant to use.

    Parameters
    ----------
    name
        A provider (claude, codex, ...). Omit to list.
    state
        ``on`` or ``off``.
    """


    policy = Policy.load()
    if name is not None:
        if state not in ("on", "off"):
            print(f"say 'on' or 'off' for {name!r} — not {state!r}", file=sys.stderr)
            raise SystemExit(2)
        if name not in PROVIDERS:
            print(f"unknown provider {name!r}; interact knows: {', '.join(PROVIDERS)}",
                  file=sys.stderr)
            raise SystemExit(2)
        policy.set_provider_active(name, state == "on")
        print(f"{name} {state}")
        return
    for p in PROVIDERS.values():
        switch = "on" if policy.provider_active(p.name) else "off"
        avail = "available" if p.available() else f"not installed (no {p.binary!r} on PATH)"
        note = f" — {p.caveat}" if not p.verified else ""
        # `<name> <on|off>` first: the panel's toggle parses exactly those two tokens.
        print(f"{p.name:8} {switch:3} {avail}{note}")
        if definitions := p.agent_definitions():
            print(f"           agents: {', '.join(definitions)}")
        if modes := p.permission_modes():
            print(f"           permission modes: {', '.join(m.id for m in modes)}")


async def _run_agent_for_cli(provider, task, **kwargs):
    """Indirection the tests replace — spawning for real costs money and a live CLI."""

    return await run_agent(provider, task, **kwargs)


def _agent_runner():
    """Honor an explicitly replaced CLI runner while command code remains deferred."""
    cli_module = sys.modules.get("interact.cli.app")
    return getattr(cli_module, "_run_agent_for_cli", _run_agent_for_cli)


@agents_app.command(name="definitions")
def agents_definitions(provider: str = "claude") -> None:
    """Print the agent definitions this CLI can resolve, one per line.

    Machine-readable on purpose: the panel's picker was scraping the human `agents providers`
    output, so a wording change would have silently emptied it. Nothing is printed when there are
    none — prose here would be parsed as an agent called "no agents found".
    """

    for name in provider_for(provider).agent_definitions():
        print(name)


@agents_app.command(name="discovered")
def agents_discovered() -> None:
    """Print the agent sessions interact did NOT start, one JSON object per line.

    Your own editor windows. They have no record on disk — they are found by asking each provider
    at list time — so a front end that reads the registry directory (the VS Code panel does)
    cannot see them at all, however many icons it has for them.

    One object per line rather than one array: a front end can parse incrementally, and a
    truncated write costs one session rather than the whole list. Nothing is printed when there
    are none, and a provider that cannot look is skipped rather than taking the caller down with
    it — a failed discovery must never blank a panel that was otherwise fine.
    """


    try:
        found = reg._discover_foreign()
    except (OSError, ValueError) as e:
        # Loud, on stderr, non-zero — never a silent empty answer. Each provider already swallows
        # its own failure, so reaching here means a real bug, and printing nothing would make that
        # indistinguishable from "you have no other sessions": the panel would cache the empty
        # answer and re-cache it every refresh with no line anywhere saying why.
        print(f"ERROR: could not ask the providers what is running — {e}", file=sys.stderr)
        raise SystemExit(1) from None
    for raw in found:
        # The RECORD builds itself. This used to re-declare the same nine fields, and a field
        # added to AgentRun would have reached the listing and not this JSON — which the VS Code
        # panel parses, so the panel would silently lack it with nothing to notice.
        run = reg.AgentRun.from_foreign(raw)
        if run is not None:
            print(run.model_dump_json())


@agents_app.command(name="modes")
def agents_modes(provider: str = "claude") -> None:
    """Print the permission modes this CLI accepts, one tab-separated row per mode.

    ``id<TAB>label<TAB>what it lets the agent do<TAB>yes|no`` — the last column being whether the
    mode acts without asking, so a front end can mark it without inferring danger from wording.
    Machine-readable for the same reason `agents definitions` is: the panel used to scrape the
    human table, and a rewording emptied it silently.

    Nothing is printed for a provider whose flags we have not verified against a real binary —
    prose here would be parsed as a mode called "no modes found".
    """

    for mode in provider_for(provider).permission_modes():
        print(f"{mode.id}\t{mode.label}\t{mode.detail}\t{'yes' if mode.unrestricted else 'no'}")


@agents_app.command(name="spawn")
def agents_spawn(task: str, provider: str = "claude", agent: str | None = None,
                 name: str | None = None, model: str | None = None,
                 cwd: str | None = None, permission_mode: str | None = None) -> None:
    """Start an agent and return its id immediately, without waiting for it to finish.

    `agents run` streams until the agent is done, which is right at a terminal and useless to a
    UI — the panel needs the id NOW so it can show the agent working. Nothing is lost by letting
    go: the child leads its own session and writes its own stream, so it outlives this process.
    """


    async def _go():
        handle = await _agent_runner()(
            provider_for(provider), task, name=name or agent or provider,
            cwd=cwd or os.getcwd(), agent=agent, model=model,
            permission_mode=permission_mode,
        )
        # Give the child a moment to be alive before this process exits out from under it.
        await asyncio.sleep(0.2)
        return handle.run_id

    try:
        print(asyncio.run(_go()))
    except (ValueError, RuntimeError) as e:
        # The argv builder validates the permission mode, four frames down; a criterion nothing
        # clears, a profile that does not exist and a provider switched off refuse the same way.
        # Without this the CLI printed its traceback where every other interact failure prints
        # one actionable line.
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(2) from None


@agents_app.command(name="run")
def agents_run(task: str, provider: str = "claude", agent: str | None = None,
               name: str | None = None, model: str | None = None, cwd: str | None = None,
               permission_mode: str | None = None) -> None:
    """Spawn an agent and stream its events until it finishes.

    ``--agent`` names a definition the CLI resolves itself (Claude Code reads
    ``~/.claude/agents/<name>.md``), so the run IS that agent and is named after it.
    """


    async def _go() -> int:
        prov = provider_for(provider)
        handle = await run_agent(prov, task, name=name or agent or prov.name,
                                 cwd=cwd or os.getcwd(), agent=agent, model=model,
                                 permission_mode=permission_mode)
        print(f"run_id {handle.run_id}")
        seen = 0
        while True:
            events = reg.read_events(handle.run_id)
            for event in events[seen:]:
                print(f"  {event.kind:11} {event.summary(viewer=handle.run_id)}")
            seen = len(events)
            if handle.process.returncode is not None:
                break
            await asyncio.sleep(0.4)
        return await handle.wait()

    try:
        raise SystemExit(asyncio.run(_go()))
    except (ValueError, RuntimeError) as e:
        # The argv builder validates the mode; without this the CLI printed its traceback while
        # every other interact failure prints one line an agent (or a person) can act on.
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(2) from None
