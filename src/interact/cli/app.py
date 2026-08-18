"""Unified ``interact`` command line — one entry point for every front-end.

``interact mcp`` runs the stdio MCP server (what clients launch); the rest give
non-VS-Code clients parity with the extension's UI: ``install`` registers the server
with a client, ``config`` persists model/key settings, ``doctor``/``providers`` report
the environment. Heavy modules (the server, the model registry, Playwright) are
imported inside the commands that need them so ``--help``, ``install`` and ``config``
start instantly.
"""

from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter

from interact import installed_version
from interact.cli.clients import ClientTarget, MCPServer, Scope
from interact.config import UserConfig

app = App(
    name="interact",
    version=installed_version(),
    version_flags=["--version", "-v"],  # `-v` too — the obvious alias users reach for
    help="Browser + desktop automation MCP server, plus tools to install and configure it.",
)


def _print_resolved_models(indent: str = "  ") -> None:
    """Print which model each VLM TASK resolves to with the current keys — the answer to "what runs
    when I do X, and why that default?". Organised BY TASK (what a user actually picks) with the
    config knob (the role) named in brackets, so it's clear different jobs can have different defaults
    — without a separate model setting per task (they'd all resolve to the same best VLM). The real
    axes are MODALITY (image/component/video/audio) and STAKES: review_ui/verify_ui layer a quality
    tier on the image model — a cheap private sovereign GLM at low/medium, the frontier image model at
    high/critical. Shared by status / providers / doctor / version so every surface tells one story."""
    from interact.models import Model
    from interact.runtime import config

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


@app.command
def version() -> None:
    """Print the installed interact version (same as `interact --version`/`-v`)."""
    print(installed_version())


def _print_stale_servers(indent: str = "  ", fix: bool = False) -> None:
    """Flag any RUNNING MCP server that loaded an OLDER version than is now available — the silent
    stale-server trap (a long-lived `interact mcp` keeps serving the code it imported at startup, so
    a shipped fix never reaches it until reconnected). Names the pid so the user knows which editor
    window's interact MCP server to reconnect. With ``fix=True`` (``interact doctor --fix``) it
    restarts them itself (SIGTERM → the editor respawns interact on current code). Nothing printed
    when every server is current."""
    from interact.server_registry import latest_version, stale_servers

    stale = stale_servers()
    if not stale:
        return
    latest = latest_version()
    if fix:
        from interact.server_registry import kill_stale_servers

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


def _print_sandboxes(real_display: str | None) -> None:
    """Which sandbox displays exist right now, and who owns each.

    Answers "why do I see two Xephyr windows?" — every interact server owns its own sandbox, so
    one window per server that has launched something is BY DESIGN. What is not by design is a
    window whose owner is gone, which is called out here and swept on the next launch.
    """
    from interact.desktop import orphans

    try:
        servers = orphans._list_x_servers()
    except Exception:
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


@app.command
def mcp() -> None:
    """Run the MCP server over stdio. Clients launch this; register it with `interact install`."""
    # Keys/settings (config.env + project .env) are loaded centrally in main() before dispatch.
    from interact.server import main as serve  # deferred: pulls in Playwright + litellm + FastMCP

    serve()


@app.command
def status(
    project: Annotated[Path, Parameter(name=["--project", "-p"])] = Path("."),
) -> None:
    """Show how interact is set up: which clients it's registered with, the configured
    models and desktop target, which API keys are present, and recent usage. The
    at-a-glance overview for a normal user (grounding/scenario probes live in the tests).

    Parameters
    ----------
    project
        Project root to check for project-scoped client registrations (default: cwd).
    """
    from interact.cli.clients import ClientTarget
    from interact.models import Model, ModelCapability
    from interact.runtime import config
    from interact.cli.usage import UsageReport

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

    print("\nModels (what your keys resolve to — pin via `interact config set`):")
    _print_resolved_models()
    from interact.desktop.backend import desktop_supported

    if not desktop_supported():
        print("  desktop    not available on this OS (Linux/X11 only) — browser automation works here")
    else:
        target_line = f"target={config.desktop_target}"
        if config.desktop_target == "nested":
            target_line += f"  headless={config.nested_headless}  display=:{config.nested_display}"
        print(f"  desktop    {target_line}")

    Model.load_registry()
    providers = Model.available_providers()
    grounding = Model.available_by_capability(ModelCapability.GUI_GROUNDING)
    print(f"\nAPI keys: {', '.join(providers) or 'none — interact config set OPENAI_API_KEY …'}")
    print(f"Grounding models ready: {len(grounding)}")

    report = UsageReport.build(since_days=30)
    print(f"\nUsage (last 30d): {report.entries} calls, ${report.total_cost:.4f}   (details: interact usage)")


@app.command
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

    server = MCPServer.resolve(dev_from=dev_from)
    result = target.install(server, scope, project.resolve(), dry_run)
    icon = {"wrote": "✓ wrote", "ran": "✓ ran", "manual": "→ manual", "skipped": "• skipped"}[result.action]
    print(f"{icon}: {target.label}  [{result.target}]")
    if result.detail:
        print(result.detail)
    print(f"\nLaunches: {server.command} {' '.join(server.args)}")
    print(f"Docs: {target.doc_url}")
    if target.note and result.action in ("wrote", "ran"):
        print(f"Note: {target.note}")


@app.command
def providers() -> None:
    """List providers and grounding models available in the current environment."""
    from interact.models import Model, ModelCapability

    Model.load_registry()
    available = Model.available_providers()
    print(f"Available providers ({len(available)}): {', '.join(available) or 'none — no API keys found'}")

    print("\nResolved selection (what each tool uses, given your keys):")
    _print_resolved_models()

    grounding = Model.available_by_capability(ModelCapability.GUI_GROUNDING)
    print(f"\nGrounding models ready ({len(grounding)}):")
    for model in grounding:
        print(f"  {model.id:<40} ${model.cost_score:.2f}/Mtok")


@app.command
def dashboard() -> None:
    """Show the status dashboard (providers, models, grounding) in the terminal.

    Renders the same declarative `View` an HTTP endpoint will serve to the browser
    and the VS Code webview — defined once, shown on every surface. No VLM calls.
    """
    from interact.cli.render import CliRenderer
    from interact.runtime import config
    from interact.cli.view import View

    CliRenderer.render(View.dashboard(config))


@app.command
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
    from interact.cli.usage import UsageReport, default_log_path

    log_path = default_log_path()
    report = UsageReport.build(since_days=days)
    window = f"last {days}d" if days else "all time"
    if report.entries == 0:
        where = "no calls recorded yet" if not log_path.exists() else f"no calls in the {window}"
        print(f"interact usage ({window}): {where}\n  log: {log_path}")
        return

    print(f"interact usage ({window}) — {report.entries} calls, ${report.total_cost:.4f}, "
          f"{report.total_input:,} in / {report.total_output:,} out tokens\n")
    print(f"  {'model':<40} {'calls':>6} {'in':>10} {'out':>10} {'cost':>10}")
    for group in report.by_model:
        print(f"  {group.name:<40} {group.calls:>6} {group.input_tokens:>10,} "
              f"{group.output_tokens:>10,} ${group.cost:>9.4f}")
    if len(report.by_provider) > 1:
        print("\n  by provider:")
        for group in report.by_provider:
            print(f"  {group.name:<40} {group.calls:>6} {' ':>10} {' ':>10} ${group.cost:>9.4f}")


@app.command
def update(check: Annotated[bool, Parameter(name=["--check", "-c"])] = False) -> None:
    """Update interact to the latest GitHub release (or just check with --check).

    Parameters
    ----------
    check
        Only report whether an update is available; don't install it.
    """
    import shutil
    import subprocess

    from interact.cli.update import REPO, available_update, installed_version

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


@app.command
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
    from interact import feedback

    print(feedback.report(title, body, kind))


@app.command
def doctor(*, fix: bool = False) -> None:
    """Diagnose the environment: command, providers, Playwright, desktop capture.

    Parameters
    ----------
    fix
        Restart any stale `interact mcp` server (it respawns on current code from your editor) —
        the one-step cure for "I shipped the fix but the bug persists".
    """
    import os
    import shutil

    from interact.models import Model, ModelCapability

    print("interact doctor\n")
    _print_stale_servers(fix=fix)
    print(f"  command       : {shutil.which('interact') or 'NOT on PATH'}")
    print(f"  config file   : {UserConfig.PATH} ({'present' if UserConfig.PATH.exists() else 'absent'})")

    try:
        import playwright  # noqa: F401

        print(f"  playwright    : installed (browser: {os.environ.get('INTERACT_BROWSER_TYPE', 'chromium')})")
    except ImportError:
        print("  playwright    : MISSING — run `uv run playwright install`")

    from interact.desktop.backend import desktop_supported
    from interact.runtime import config

    # Desktop diagnostics are Linux/X11-specific (maim, /dev/uinput, Xephyr). On macOS/Windows
    # they'd print misleading "MISSING (apt install …)" / "udev rule" advice, so report cleanly
    # that desktop automation is N/A here and browser automation is the ready path.
    if not desktop_supported():
        import platform as _pf

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
    print(f"  providers     : {', '.join(available) or 'none — set a provider API key'}")
    print(f"  grounding     : {len(grounding)} model(s) ready")
    print("  selection     : (what each tool resolves to — answers 'why is my default X?')")
    _print_resolved_models(indent="    ")


config_app = App(name="config", help="Persist model/key settings to ~/.interact/config.env.")
app.command(config_app)


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


def main() -> None:
    from interact.versioning import force_utf8_io

    force_utf8_io()  # UTF-8 stdout so glyphs (✓, →) don't crash on Windows' cp1252 console
    # Load keys/settings once for EVERY command: persisted config first, then a project
    # `.env` (both override=False, so precedence is host env > config.env > .env).
    # Centralised here so providers/doctor/status/dashboard, the TUI and the server all
    # see the same keys — previously only `mcp` loaded .env, so `interact providers`
    # reported none inside a checkout that had a .env.
    UserConfig.apply()
    from interact.config import load_dotenv_for_cli

    load_dotenv_for_cli()
    # Bare `interact` in a terminal opens the configuration TUI (configure models/keys,
    # see bindings, view usage — no commands to memorise). With args, or when stdout
    # isn't a TTY (piped/scripted), behave as the normal command-line app.
    import sys

    if len(sys.argv) == 1 and sys.stdout.isatty():
        from interact.cli.tui import run as run_tui

        run_tui()
        return
    app()


agents_app = App(name="agents", help="Spawn and supervise agent runs across providers.")
app.command(agents_app)


@agents_app.command(name="list")
def agents_list(foreign: bool = True) -> None:
    """Show agent runs: status, what each is doing, and API-equivalent cost.

    Parameters
    ----------
    foreign
        Also show agent sessions interact did not start (your own editor windows).
    """
    from interact.agents import registry as reg

    runs = reg.list_runs(include_foreign=foreign)
    if not runs:
        from interact.agents.providers import available_providers

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
    from interact.agents import registry as reg

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
    from interact.agents import registry as reg

    resolved = reg.resolve_run_id(run_id)
    if resolved is None:
        print(f"No agent run {run_id!r}.")
        return
    print(f"Stopped {resolved[:8]}." if reg.stop(resolved) else f"No agent run {run_id!r}.")


@app.command(name="refresh")
def refresh_live_data() -> None:
    """Re-fetch the live model catalog and benchmark scores the dashboard reads.

    Python is the SOLE writer of those cache files — the extension used to fetch and write the
    catalog itself with a narrower schema, so whichever side wrote last decided whether prices
    existed. Now the extension asks for this instead.
    """
    from interact import live_sources

    done = live_sources.refresh_all()
    print("Refreshed: " + ", ".join(done) if done else "Nothing refreshed (offline, or no API key).")


@agents_app.command(name="send")
def agents_send(run_id: str, message: str) -> None:
    """Send a message to a running agent — it answers with its full context intact.

    This is how the VS Code panel lets you join the conversation instead of only watching it: the
    agent resumes its own session, so it remembers what it has already done and its reply lands in
    the same transcript the panel shows.
    """
    import subprocess

    from interact.agents import messaging
    from interact.agents import registry as reg
    from interact.agents.providers import provider_for

    run, error = messaging.check_deliverable(run_id)
    if error:
        print(error)
        return
    run_id = run.run_id  # deliver against the full id, whatever prefix was typed
    if error := messaging.record_exchange(messaging.sender_id(), run_id, message):
        print(error)
        return
    raw = reg.raw_events_path(run_id)
    raw.parent.mkdir(parents=True, exist_ok=True)
    argv = provider_for(run.provider).resume_command(run_id, message)
    with raw.open("ab") as sink:  # append: another turn of the same conversation
        try:
            subprocess.Popen(argv, cwd=run.cwd or ".", stdout=sink,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            print(f"ERROR: could not deliver to {run.name} — {e}")
            return
    print(f"Delivered to {run.name} ({run_id[:8]}). It is answering now.")


@agents_app.command(name="clear")
def agents_clear(run_id: str | None = None) -> None:
    """Forget finished agent runs — all of them, or one by the short id `agents list` prints.

    A running agent is never forgotten: its record is the only handle on the process.
    """
    from interact.agents import registry as reg

    if run_id:
        print(f"Forgot {run_id}." if reg.forget(run_id)
              else f"Kept {run_id!r} — unknown, or still running.")
        return
    cleared = reg.clear_finished()
    print(f"Forgot {len(cleared)} finished run(s)." if cleared else "Nothing finished to clear.")


@agents_app.command(name="providers")
def agents_providers() -> None:
    """Which agent CLIs can be spawned here, and the named agents each can resolve."""
    from interact.agents.providers import PROVIDERS

    for p in PROVIDERS.values():
        state = "available" if p.available() else f"not installed (no {p.binary!r} on PATH)"
        note = f" — {p.caveat}" if not p.verified else ""
        print(f"  {p.name:8} {state}{note}")
        if definitions := p.agent_definitions():
            print(f"           agents: {', '.join(definitions)}")


async def _run_agent_for_cli(provider, task, **kwargs):
    """Indirection the tests replace — spawning for real costs money and a live CLI."""
    from interact.agents.run import run_agent

    return await run_agent(provider, task, **kwargs)


@agents_app.command(name="definitions")
def agents_definitions(provider: str = "claude") -> None:
    """Print the agent definitions this CLI can resolve, one per line.

    Machine-readable on purpose: the panel's picker was scraping the human `agents providers`
    output, so a wording change would have silently emptied it. Nothing is printed when there are
    none — prose here would be parsed as an agent called "no agents found".
    """
    from interact.agents.providers import provider_for

    for name in provider_for(provider).agent_definitions():
        print(name)


@agents_app.command(name="spawn")
def agents_spawn(task: str, provider: str = "claude", agent: str | None = None,
                 name: str | None = None, model: str | None = None,
                 cwd: str | None = None) -> None:
    """Start an agent and return its id immediately, without waiting for it to finish.

    `agents run` streams until the agent is done, which is right at a terminal and useless to a
    UI — the panel needs the id NOW so it can show the agent working. Nothing is lost by letting
    go: the child leads its own session and writes its own stream, so it outlives this process.
    """
    import asyncio
    import os

    from interact.agents.providers import provider_for

    async def _go():
        handle = await _run_agent_for_cli(
            provider_for(provider), task, name=name or agent or provider,
            cwd=cwd or os.getcwd(), agent=agent, model=model,
        )
        # Give the child a moment to be alive before this process exits out from under it.
        await asyncio.sleep(0.2)
        return handle.run_id

    print(asyncio.run(_go()))


@agents_app.command(name="run")
def agents_run(task: str, provider: str = "claude", agent: str | None = None,
               name: str | None = None, model: str | None = None, cwd: str | None = None) -> None:
    """Spawn an agent and stream its events until it finishes.

    ``--agent`` names a definition the CLI resolves itself (Claude Code reads
    ``~/.claude/agents/<name>.md``), so the run IS that agent and is named after it.
    """
    import asyncio
    import os

    from interact.agents import registry as reg
    from interact.agents.providers import provider_for
    from interact.agents.run import run_agent

    async def _go() -> int:
        prov = provider_for(provider)
        handle = await run_agent(prov, task, name=name or agent or prov.name,
                                 cwd=cwd or os.getcwd(), agent=agent, model=model)
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

    raise SystemExit(asyncio.run(_go()))
