# interact project instructions

Canonical project rules. Provider files point here. Say nothing the code already enforces or the
durable paradigms already carry — `bs-detector` verdicts an edit here before it lands.

## Product model

`interact` gives an agent eyes and hands. Its surfaces, none of them primary:

- MCP server — for agents working in code.
- CLI — terminal workflows.
- VS Code extension and its webviews.
- Website — what it does, and how to install it on each platform.
- Web platform — served by the private half, not in this repository.

Public and private halves:

- This repository is the PUBLIC half: it parses, asks the server for what it needs, and puts the
  answer to work across the surfaces above.
- The server is PRIVATE and lives in its own repository — tenants, auth, billing, secrets, queues,
  retention, deployment. It consumes a released public schema version and is never imported here.

Ownership (short names map to `packages/interact-core` and `packages/interact-local`):

- `interact-core` — provider-independent contracts and generated API models shared by every surface.
  Source of truth for tool APIs, schemas and payloads; the tool docstrings carry the behaviour. An
  old parameter or tool name survives only if `interact-core` still declares it.
- `interact-local` — the local implementation: `server` (service lifecycle, target resolution,
  capture, analysis dispatch, tool surfaces), `desktop` (isolated displays, input, windows,
  coordinates, recording, accessibility), `cli`, and `config` (typed settings plus the schema every
  front end reads).
- `clients/vscode` — extension and webviews; TypeScript bindings are generated from the Python models.
- `site` — the public website.
- `tests` — unit and integration. Real-model suites are key-gated and excluded from regular unit runs.

## Prompts

Prompt source is the git worktree at `${XDG_DATA_HOME:-~/.local/share}/interact/prompts`: edit it,
then `interact prompts commit` and `push` to its git remote, then `publish <endpoint> <token-file>`
to put it on the service (refused unless HEAD matches upstream). Clients only read. `prompts/` in
this repository holds distributable defaults; indexes and mirror caches are derived — never edit them.

## Team

- Delegate independent, file-scoped work with explicit boundaries and write authority. At most three
  child workers alive.

## Delivery

A change crossing an external seam — server, provider API, prompt sync, browser/desktop tools,
extension host, audio/video paths — needs one real integration check.

A user-facing interaction claim needs rendered evidence, in this order: an interact target surface
in an isolated target, a nested display capture, a browser/WebView capture with the interaction
exercised. If the environment cannot produce one, record the blocker and leave the claim open.

## Security and credentials

- Never read or print credentials, tokens, private keys, `.env`, keyrings, or unrelated environment
  secrets. The staged-diff scan in `.githooks/pre-commit` blocks a commit carrying them; it does not
  clean the diff for you.
- No push, release, deploy, or close-external action without explicit authorization.
