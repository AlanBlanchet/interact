import os
from pathlib import Path
import shutil
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

# Set BEFORE any interact module is imported: importing `interact.runtime` loads the model
# registry, which now asks a running Ollama daemon what it has. A unit test must never reach the
# network — and on a developer box with a real daemon it silently would. `setdefault` so an
# integration run can force it back on.
#
# The name is deliberately NOT `INTERACT_`-prefixed: `_LiveConfig.refresh()` deletes every
# `INTERACT_*` var that config.env does not define, and any test whose code path refreshes config
# (every `@instrumented` MCP tool does) would silently re-enable discovery for the REST of the run.
os.environ.setdefault("OLLAMA_DISCOVERY", "0")
# Unit tests retain the historical mocked-LiteLLM default.  Production Config defaults to the
# subscription session path; the explicit test override prevents an old test that patches only
# `_vision_completion` from launching the user's real Claude/Codex login by accident.
os.environ.setdefault("INTERACT_MEDIA_BACKEND", "api")
os.environ.setdefault("INTERACT_MEDIA_BILLING", "api_allowed")

from interact.agents.providers import AgentProvider, ClaudeCodeProvider


@pytest.fixture(scope="session", autouse=True)
def _load_repo_dotenv() -> None:
    """Load nearest `.env` via the shared CLI loader (override=False)."""
    from interact.config import load_dotenv_for_cli

    load_dotenv_for_cli()


@pytest.fixture(autouse=True)
def _default_unit_media_to_mocked_api(monkeypatch):
    """Re-apply after every live-config refresh, which intentionally clears file-absent env keys."""
    monkeypatch.setenv("INTERACT_MEDIA_BACKEND", "api")
    monkeypatch.setenv("INTERACT_MEDIA_BILLING", "api_allowed")


@pytest.fixture(autouse=True)
def _block_real_vlm_calls(request):
    """Unit tests must NEVER make a real model/provider call. Such a call can hang forever
    on an interactive auth flow (e.g. litellm's chatgpt device-code poll) or slow network —
    which is exactly what stalled CI. Block litellm's entry points so any un-mocked path
    fails fast with a clear message instead of hanging. Integration tests opt out."""
    if "integration" in request.keywords:
        yield
        return
    import litellm

    def _blocked(*_a, **_k):
        raise RuntimeError(
            "real litellm call blocked in a unit test — mock analyze_media/the VLM, "
            "or mark the test `integration`"
        )

    async def _ablocked(*_a, **_k):
        _blocked()

    saved = (
        litellm.acompletion,
        litellm.completion,
        litellm.acreate_file,
        litellm.atranscription,
        litellm.transcription,
    )
    litellm.acompletion, litellm.completion = _ablocked, _blocked
    litellm.acreate_file = _ablocked
    litellm.atranscription, litellm.transcription = _ablocked, _blocked
    try:
        yield
    finally:
        (
            litellm.acompletion,
            litellm.completion,
            litellm.acreate_file,
            litellm.atranscription,
            litellm.transcription,
        ) = saved


@pytest.fixture(autouse=True)
def _block_real_subscription_cli(monkeypatch, request):
    """A unit test may use a fake executable, but may never spend the user's plan allowance."""
    if "integration" in request.keywords:
        return
    real = {
        Path(path).resolve()
        for name in ("claude", "codex")
        if (path := shutil.which(name)) is not None
    }
    original = AgentProvider.subscription_authenticated
    original_process = ClaudeCodeProvider.run_media_process

    async def guarded(self, env, *, timeout=10):
        executable = Path(self.executable()).resolve()
        if executable in real:
            raise RuntimeError(
                "real subscription CLI blocked in a unit test — use a fake executable"
            )
        return await original(self, env, timeout=timeout)

    async def guarded_process(self, argv, **kwargs):
        if argv and Path(argv[0]).resolve() in real:
            raise RuntimeError(
                "real subscription CLI process blocked in a unit test — use a fake executable"
            )
        return await original_process(self, argv, **kwargs)

    monkeypatch.setattr(AgentProvider, "subscription_authenticated", guarded)
    monkeypatch.setattr(ClaudeCodeProvider, "run_media_process", guarded_process)


@pytest.fixture(autouse=True)
def _isolate_interact_logs(tmp_path):
    """Keep test artifacts out of the user's real ~/.interact/logs: route Debug dumps to a per-test
    tmp via the screenshot_dump_dir override, which survives config.refresh() (unlike a plain field
    set, which review_ui's refresh would reset). A test that needs the real dump path overrides it."""
    from interact.runtime import config

    saved = (config.screenshot_dump_dir, config.media_backend, config.media_billing)
    config.screenshot_dump_dir = tmp_path / "interact-debug"
    config.media_backend = "api"
    config.media_billing = "api_allowed"
    try:
        yield
    finally:
        config.screenshot_dump_dir, config.media_backend, config.media_billing = saved


def pytest_collection_modifyitems(config, items):
    # integration → needs API keys + a real browser; desktop → needs a live Linux display.
    # Skipping these keeps the suite green on macOS/Windows (and headless CI), so the
    # cross-OS matrix exercises the OS-agnostic code without false failures.
    no_key = not os.environ.get("OPENAI_API_KEY")
    no_linux_display = sys.platform != "linux" or not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )
    skip_integration = pytest.mark.skip(reason="No OPENAI_API_KEY set")
    skip_desktop = pytest.mark.skip(reason="desktop tests need Linux + a live display")
    for item in items:
        if no_key and "integration" in item.keywords:
            item.add_marker(skip_integration)
        if no_linux_display and "desktop" in item.keywords:
            item.add_marker(skip_desktop)

@pytest.fixture
def http_origin(tmp_path):
    """A real http origin serving one static page, for anything the browser keys by ORIGIN —
    localStorage above all: a `data:` / `about:blank` page has an opaque origin, so state set there
    never survives anything and a test on it proves nothing. Yields the origin (no trailing slash)."""
    (tmp_path / "index.html").write_text("<title>origin</title><body>served</body>")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


# --- shared image fixtures (blankness, capture and VLM-gate tests all build frames) ---


def make_png(fill=(0, 0, 0), size=(320, 200), speckle: int = 0) -> bytes:
    """A flat frame, optionally speckled — what a crashed or unmapped window grabs as."""
    import io

    from PIL import Image

    img = Image.new("RGB", size, fill)
    for i in range(speckle):
        img.putpixel((i % size[0], (i * 7) % size[1]), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_varied_png(size=(320, 200)) -> bytes:
    """A frame with content in it, for the negative case."""
    import io

    from PIL import Image

    img = Image.new("RGB", size)
    for x in range(size[0]):
        for y in range(size[1]):
            img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
