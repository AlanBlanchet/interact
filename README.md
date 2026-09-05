<p align="center">
  <a href="https://alanblanchet.github.io/interact/">
    <img src="site/assets/banner.png" alt="interact — give your agent eyes and hands" width="820">
  </a>
</p>

## Repository boundaries

This public repository is one release graph with explicit product homes:

- `packages/interact-local` owns the `interact` Python import, CLI, MCP server, automation, local
  sessions, and explicit API routes.
- `packages/interact-contracts` owns dependency-light prompt distribution contracts and their
  generated JSON Schema; `clients/vscode` consumes the generated TypeScript form.
- `clients/vscode` owns the VS Code extension, and `site` owns the static public website boundary.
- Librarian-edited Markdown under `prompts` is canonical source. Private tenant, authentication,
  billing, secrets, queues, retention, and deployment code never enters this repository.

The packages version together from root `pyproject.toml`. Local-session and local-compute routes
remain distinct from separately billed `metered_api` routes; failure never silently crosses that
charge boundary, and a vendor subscription is not described as universally free. Private services
consume a released public schema version from their own repository and are never imported here.

### Prompt distribution foundation

Librarians edit `prompts/manifest.json` and its referenced Markdown files; the manifest digest is
validated before publication. Start the private sibling service locally with:

```bash
cd ../interact-cloud
uv run python -m interact_cloud --database out/local-cloud.sqlite3 --ready out/ready.json
```

`interact.prompt_client._PromptClient.sync(account, cache)` downloads the authenticated typed
catalog and exact immutable revisions into an account-scoped `_PromptCache`. A conversation start
may carry a `PromptSelection` beside the user's ordinary `prompt`. The shipped console syncs and
exactly resolves that selection itself, sends the verified content as the provider's system or
developer instruction, keeps the user's question as the user turn, and persists the resulting
server-derived `PromptExecutionRef` on `AgentRun`. Missing, oversized, unauthorized, or mismatched
revisions fail before provider startup and never select another prompt or charge route.

The executable local file-to-HTTP-to-cache control is:

```bash
cd ../interact-cloud
PYTHONPATH=../interact/packages/interact-local/src:../interact/packages/interact-contracts/src:src \
  uv run pytest tests/test_http.py::test_real_http_process_enforces_tenant_non_disclosure -q
```

<p align="center">
  <b>Browser <i>and</i> desktop automation for AI agents — over MCP.</b><br>
  Vision-grounded control that reports <b>what changed</b>, not a screenshot.
</p>

<p align="center">
  <a href="https://alanblanchet.github.io/interact/"><b>🌐 Website</b></a> ·
  <a href="#60-second-quickstart">Quickstart</a> ·
  <a href="#ask-your-agent">Examples</a> ·
  <a href="#what-your-agent-can-do">Capabilities</a>
</p>

<p align="center">
  <a href="https://github.com/AlanBlanchet/interact/actions/workflows/ci.yml"><img src="https://github.com/AlanBlanchet/interact/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-server-black.svg" alt="MCP"></a>
</p>

---

## See it work

Your agent clicks a filter, types a search, adds to a cart. Each caption is the tool call that ran
and the text that came back — that text is all your model sees.

<p align="center"><img src="site/assets/demo-browser.gif" alt="An agent driving a web store: clicking the Audio filter narrows the list to 2 products, typing 'field' narrows it to 1, and Add to cart takes the cart from 0 to 1" width="760"></p>

The same tools drive a **real desktop app** — `launch_app` puts it in an isolated display the agent owns.

<p align="center"><img src="site/assets/demo-desktop.gif" alt="An agent launching gnome-calculator into interact's sandbox and clicking 7 x 6 = , the app showing 42" width="380"></p>

## 60-second quickstart

```bash
# 1. install the `interact` command (installs uv if missing)
curl -LsSf https://raw.githubusercontent.com/AlanBlanchet/interact/main/install.sh | sh

# 2. register it with Codex
interact install codex

# 3. start a fresh Codex session (or restart the IDE extension), then verify
codex mcp get interact

# 4. check keys, providers, browser, desktop
interact doctor
```

That's it — your agent can now navigate, click, type, scroll, drag, see, hear and watch.

Other hosts use the same bootstrap: `interact install claude`, `cursor`, `vscode`, `copilot`,
`windsurf`, `zed`, or `claude-desktop`.

<details>
<summary>Other install routes (Windows, no-install, VS Code)</summary>

```bash
uv tool install git+https://github.com/AlanBlanchet/interact             # any platform, incl. Windows
uvx --from git+https://github.com/AlanBlanchet/interact interact mcp     # run without installing
```

interact isn't on PyPI — the bare name is taken there. `interact install vscode` registers the server
with Copilot's agent mode; no extension needed.
</details>

## Ask your agent

Plain English in, real actions out. Nothing to script — these are prompts you type to your agent.

> **"Open the store on localhost:3000, filter to Audio, add the field recorder to the cart and tell me the cart count."**
> `navigate` opens the page, then one `run_actions` batches the clicks and typing — each step reporting what changed. *(This is the browser demo above.)*

> **"Launch gnome-calculator in the sandbox and work out 7 × 6."**
> `launch_app` starts it on a display the agent owns; `run_actions` with `target="nested:Calculator"` presses the keys and reads the result back. *(This is the desktop demo above.)*

> **"Review the checkout page for visual defects, then confirm the nav has 4 tabs."**
> `review_ui` returns a severity-sorted critique, `verify_ui` answers PASS/FAIL per requirement, and `measure_ui` backs it with an exact WCAG contrast ratio — no model call, no spend.

## What your agent can do

One tool per job. The generic ones take a `target` — unset for the browser, a window title, `screen`,
`nested:<title>` for the sandbox, or `file:<path>` to analyse an image you already have.

| Tool | What it does |
| --- | --- |
| `run_actions` | The workhorse — click, type, scroll, drag, key-press, `evaluate_js`, batched in one call, each step reporting what changed. |
| `navigate` | Open a URL; returns title + visible text, or a vision answer with `query`. |
| `screenshot` | Capture a page, window or screen. Add `query` for an interpretation, `return_image` for raw pixels. |
| `get_interactive_elements` | List what's clickable as numbered `ref`s — DOM scan in the browser, vision / AT-SPI on the desktop. |
| `get_page_state` | URL, title, accessibility tree, visible text and the `ref` list. No model call. |
| `review_ui` | Find defects — a severity-sorted critique (contrast, overflow, truncation, misalignment). Pass a `reference` image to judge how a build diverges from a target. |
| `verify_ui` | Accept against your checklist — one PASS / FAIL / UNCLEAR per literal requirement, each naming the element judged. |
| `measure_ui` | Measure deterministically — exact WCAG contrast with AA/AAA, dominant colours, largest uniform band. No VLM, no spend. |
| `record` | Record a browser or desktop interaction to video, then `query` the video model about the sequence. |
| `transcribe` | Hear a local audio *or* video file — transcript back, or `query` it about the sound. |
| `launch_app` · `reset_sandbox` | Run an app in an isolated display the agent owns; tear it down again. |
| `list_desktop_windows` | List drivable targets — monitors, open windows, sandbox windows. |
| `session` · `get_logs` · `download_asset` | Browser session lifecycle, network / console logs, authenticated downloads. |
| `list_providers` · `report_issue` | What's configured, and file a bug or idea straight to the maintainers. |

### Models and keys

Visual jobs select your installed, authenticated **Claude Code session transport by
default**—including screenshot descriptions, element grounding, `review_ui` / `verify_ui`, and
sampled video/interaction analysis. Session dispatch is blocked until the explicit operator
attestation below. No API key is needed, and `session_only` prevents interact from falling through
to a metered API, but vendor CLIs can consume account-side credits after included plan usage.

Before enabling sessions, open Claude **Settings → Usage**, keep Usage credits disabled, ensure the
prepaid balance is zero, and turn auto-reload off ([Anthropic's usage-credit controls](https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans)). Anthropic's announced Agent SDK /
`claude -p` monthly-credit change was paused on June 16; `claude -p` continues to draw plan
usage limits ([Anthropic's paused-change notice](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)), but the account-side Usage-credit controls still require this guard. CLI authentication cannot verify these account settings, and a later change is a residual race interact cannot detect.
Video sessions receive ordered, timestamped frames (up to the configured frame cap; 12 by default),
rather than uploading the original clip.

The transport and spending policy are separate, explicit settings:

```bash
# Session transport, with no metered API fallback by interact.
interact config set media.backend auto               # auto | session | api
interact config set media.billing session_only       # session_only | api_allowed
interact config set media.providerOrder claude

# Only after disabling each named provider's account-side credits as described above:
interact config set media.noExtraUsageConfirmedFor claude

# Optional session model pins and process timeout.
interact config set media.claudeModel <claude-model>
interact config set media.timeout 120
```

Without that attestation, `session` is blocked; `auto+api_allowed` skips sessions and uses the
explicitly permitted API instead. To opt into metered visual fallback, set
`media.billing=api_allowed` and keep `media.backend=auto`; set `media.backend=api` to use only
the API. An explicit model override must belong to the selected provider—it is never silently
ignored.

Audio is the deliberate boundary: Claude visual sessions do not transcribe or hear audio.
With `session_only`, `transcribe` fails before any API call. With
`media.billing=api_allowed`, audio always uses the configured `audio.model` API or local-compatible
transport, even when `media.backend=session`; after a transcription-only model produces text, a
Claude session may answer questions over that transcript.

Run `interact status` to see the media backend, billing policy, ordered CLI availability, API/local
models, and usage. Run `interact` with no arguments for the terminal configuration UI. Settings live
in `~/.interact/config.env` and are also exposed by the VS Code extension.

## Platform support

| | Linux | macOS | Windows |
| --- | :-: | :-: | :-: |
| Browser, MCP server, CLI, TUI | ✅ | ✅ | ✅ |
| Desktop control (real windows) | ✅ (X11; uinput input also on Wayland) | ⏳ | ⏳ |

Browser automation works everywhere. Native desktop control is Linux/X11 today; off Linux the desktop
tools return one clear message pointing you at the browser target — macOS/Windows backends are tracked
in [#24](https://github.com/AlanBlanchet/interact/issues/24). Known X11 limits, all under
[#1](https://github.com/AlanBlanchet/interact/issues/1): GPU-rendered windows (emulators, games) grab
black without a compositor — interact says so rather than handing back a black image; a software-GL blur
can composite to a solid strip; transient popups need `target="nested"` to capture the whole sandbox.

## Development

```bash
git clone https://github.com/AlanBlanchet/interact && cd interact
uv sync
uv run pytest -m "not integration"      # fast, cross-platform suite
uv tool install --force --editable .    # put your checkout's `interact` on PATH
```

CI runs the suite on Linux/macOS/Windows plus a sandboxed Linux desktop job; on push to `main` it tags
and publishes the release from `pyproject.toml`'s version (see [RELEASING.md](RELEASING.md)).

## Contributing

Issues and PRs welcome. Please add a failing test for a bug before fixing it, keep the suite green
(`uv run pytest -m "not integration"`), and note user-facing changes in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE) © Alan Blanchet
