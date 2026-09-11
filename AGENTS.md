# interact project instructions

This file is the canonical project instruction source. Provider-specific files must import or point here; do not duplicate project rules in them.

## Product

`interact` is a Python MCP server for browser and desktop automation, with optional visual-language-model analysis. One core under `src/interact/` serves the CLI, MCP server, and VS Code extension.

- `src/interact/server/` owns the MCP instance, lifecycle, target resolution, capture, visual analysis, sandboxing, and tool surfaces.
- `src/interact/desktop/` owns desktop backends, isolated displays, input, windows, coordinates, recording, and accessibility integration.
- `src/interact/cli/` owns user commands and the terminal UI.
- `src/interact/config/` owns typed settings and the declarative settings schema used by every front end.
- `clients/vscode/` owns the TypeScript extension and webviews; Python models remain the source for generated TypeScript bindings.
- `tests/` contains unit and integration coverage. Real-model tests must be explicitly marked, key-gated, and excluded from ordinary unit runs.

The MCP tool docstrings and typed schemas are the API source of truth. Inspect them before changing or documenting a tool. Do not preserve an older parameter name or tool name merely because a provider instruction still mentions it.

Generic capture and action tools select their surface through `target`; the exact routing rules are canonical in `server/core.py`'s MCP instructions (`_instructions`) and each tool's own docstring — read them there, never restate them here. Browser-only capabilities remain separate. Do not reintroduce the obsolete split `window`/`session` guidance for generic tools.

## Prompt authoring and distribution

Personal prompts are authored in the private Git worktree at `${XDG_DATA_HOME:-~/.local/share}/interact/prompts`; they never enter this public repository. `interact prompts` is the supported authoring, history, synchronization, compilation, and installation surface. A clean committed source revision compiles into a commit-bound manifest beneath the user's Interact cache, and only a fully validated projection may be installed into Claude, Codex, or VS Code consumer locations. The source worktree is editable and available offline; caches, generated projections, provider install roots, and project-local overlays are derived and must never be hand-edited or treated as source.

The public `prompts/` package contains only distributable product defaults and schemas. Runtime prompt metadata in SQLite is a server-derived index/cache, not authoring history; Git remains the authority for prompt content, dates, ancestry, merges, and conflicts. Preserve user routing settings through the supported Interact configuration surface. Never commit a personal corpus, private overlay, or installed projection to this repository.

## Available team

The current Codex harness provides generic subagents, not a guaranteed catalog of installed named specialists. A task name and a role description create a scoped worker; they do not prove that a durable specialist prompt was loaded.

- The main thread coordinates, owns the complete acceptance ledger, and is the only project manager.
- Delegate only concrete, independent work with the relevant files, boundaries, evidence format, and write authority stated in the task.
- Describe a worker as a specialist only when its durable prompt is actually available in the active harness. Otherwise call it a generic worker assigned that responsibility.
- Do not route implementation through a fictitious named hierarchy. When no durable technical lead is installed, appoint one generic implementation lead in the task text and keep final technical verification on the main thread.
- The concurrency ceiling is four live agents including the main thread. The main thread may use at most three child slots. If a child must delegate, dispatch only that lead initially and leave two slots free. Failed over-capacity dispatches do not queue; reconcile dispatched tasks against returned tasks.
- Parallelize breadth-first read-only work. Keep shared-file edits sequential or under one write owner.

Use a stable task name. Its memory file is `.github/memory/<task-name-with-underscores-replaced-by-hyphens>.md`; the root coordinator uses `pm.md`. Do not invent a second semantic alias such as `session_research` for an existing `researcher` role. A genuinely task-specific generic worker may use a task-specific name and owns the matching normalized memory file.

## Finite request-lineage state machine

One user request is one finite request lineage. A lineage normally has one append-only iteration ledger; a valid ledger may contain multiple recovery epochs. Never edit, delete, or replace a recognized event. The nine states below describe the active epoch; move forward through them and return to the earliest invalid state when evidence fails. A quarantine successor is a second ledger in the same lineage, not a new request, and cannot expand or replace the original acceptance contract.

Before writing any event, the ledger writer must run `scripts/repository_gate.py validate-append --ledger <current-ledger> --event <proposed-json>` against the exact current prefix and one typed proposed event stored as a bounded regular file beneath the repository. Append only when that command exits zero and reports the next state. JSON or fence validity alone is not transition authority; the prospective check must execute the same sequence and binding validation as the repository gate. Validate prefix history independently, then evaluate repository-current binding against the combined prospective sequence; do not reject a legitimate `COMMITTED` or corrective typed nonzero `RED` because only the pre-append terminal state's current-binding invariant no longer holds.

If an exact quarantine manifest must exist before the first recovery baseline can be decoded, but introducing it changes the index that baseline must truthfully capture, use only a finite `single_successor` bootstrap control approved by the librarian and an independent validator. The strict control record binds the baseline and prospective-candidate index trees, the frozen predecessor ledger and first event, exact failed `validate-append` replays from an empty prefix, their sole manifest delta, and every permitted governance blob. Run `validate-bootstrap` from staged gate bytes before creating the successor. Exact reruns against unchanged bytes are idempotent; reject the authorization once any successor path exists, either the control or target manifest is committed, or any bound path, blob, candidate, or conflict check differs. The control grants no workflow, product, candidate, review, verification, commit, or closure authority; the successor still begins with an ordinary successful `validate-append`.

An iteration is closed only when the latest epoch ends in a valid `CLOSED` event with no later event. While the same request is still open and before handoff, new executable evidence may disprove a closure claim. Append `SUPERSEDED` immediately after that `CLOSED`; bind `closed_commit` to the preceding epoch's `COMMITTED` event and name the contradicted acceptance or closure claim. Resume at `DESIGNED` when the interpretation or interface was invalid, or at `RED` when implementation or verification behavior was disproved. The recovery boundary must contain structural contradictory evidence: a typed nonapproved review finding bound to the same claim before `DESIGNED`, or a nonzero command, failing assertion, and summary in the immediately following `RED`. An approved review has no findings; never infer review semantics from narrative sentinels such as `no findings`. `SUPERSEDED` is a recovery control event, not a tenth workflow state: it retains the baseline and acceptance contract, invalidates that epoch, clears its candidate, review, verification, and current-commit context, and preserves the failed close claim for audit.

Every new `SUPERSEDED` variant declares a schema version and uses a finite typed `contradicted_claim`; free-form narratives are audit detail, never authorization. Preserve earlier recognized event bytes and order. An unversioned historical variant is readable only through a tracked, immutable migration record that binds its exact raw payload digest, iteration id, ordinal, preceding closed commit, and one typed replacement meaning. Never accept legacy fields by shape, prose, runtime configuration, or a ledger-authored self-migration, and never add a wildcard migration. If recognized history was mutated, restore its last witnessed bytes before applying the migration boundary; restoration is not a schema rewrite.

Validate every historical `COMMITTED` event against its recorded commit object and candidate tree. Require only the active epoch's latest commit to equal current `HEAD`; after recovery, an earlier valid commit is historical and need not remain `HEAD`. Active-ledger discovery uses the latest unsuperseded epoch. No prose or event may follow a current valid `CLOSED` except the single recovery event above. After handoff or a new user request, defects start a new request lineage rather than reopening the old ledger.

### Structurally corrupt ledger quarantine

A malformed or structurally invalid event cannot be superseded or migrated because its boundaries carry no authority. Fail closed. Use quarantine only when the gate can reproduce one exact structural corruption and validate every event before it; never use it to abandon a valid ledger or inconvenient evidence.

Keep the private ignored predecessor ledger byte-for-byte at its original path. Do not append to it, rewrite it, move it, track it, or reinterpret its malformed content. Quarantine is an external control record, not a workflow event or state. It cannot serve as acceptance, authority, a candidate, review, verification, closure, or commit evidence.

Store one immutable tracked manifest per predecessor digest under `.github/iteration-quarantine/`, outside `.github/memory/`. Its finite schema binds the exact repository-relative predecessor path, iteration id, whole-file SHA-256 and byte size, base `HEAD`, parser failure code, first failing event ordinal and raw-block digest, trusted-prefix event count and digest, gate-derived original request and canonical acceptance digest, and one unique successor iteration id. In a multi-edge chain, derive request and acceptance from the root predecessor at every edge; no intermediate ledger may redefine either. A version-2 recovery baseline binds the indexed planned bytes and baseline state of every manifest and clears the generic predecessor context `design`, `red`, `implementation`, `candidate`, `review`, `verification`, `commit`, `closure`, and `approval`. The manifest contains no free-form prose or replacement meaning. Reject wildcards, duplicate or conflicting records, runtime configuration, and any self-migration authored by the predecessor ledger.

Before introducing a manifest, read it from the candidate index, prove that the executing gate bytes equal the staged gate blob, and require the raw local predecessor at the bound path. The gate independently identifies the first failure, reproduces the declared finite failure code, validates the complete trusted prefix including historical commit bindings, derives the original request and acceptance itself, and compares every bound digest and count. Any mismatch fails closed; a ledger that parses as valid is ineligible. Once that exact manifest is committed, a fresh clone may omit the ignored predecessor. If the private predecessor is present in any clone, its path and bytes must still match the manifest exactly.

Validate every quarantine manifest before active-ledger discovery. Exclude only a predecessor whose exact manifest is valid, then require its uniquely named successor to be the lineage's only active ledger. Explicit verification of a quarantined predecessor remains a non-success result. A manifest never makes the predecessor closed and never licenses a hook or commit without a fresh successor candidate that is independently `REVIEWED` and `VERIFIED`.

The librarian owns the quarantine contract and may authorize an exact non-destructive recovery only with an independent validator's approval of the manifest and frozen candidate. This recovery does not require new user confirmation. User authority is required when the bootstrap predecessor bytes are missing or mutated, the original request or acceptance cannot be derived exactly, or recovery presents destructive ambiguity.

### 1. BASELINED

Before any edit or branch operation, create `.github/memory/iterations/<iteration-id>.md` and record:

- the user request and checkable acceptance items;
- current branch, `HEAD`, and `git status --short` exactly;
- `git diff --binary | sha256sum`, `git diff --cached --binary | sha256sum`, and checksums for every untracked file in scope;
- which paths are pre-existing user work and must not be staged, reverted, reformatted, or attributed to this iteration;
- whether the intended files overlap the dirty baseline.

The recorded hashes are the durable pre-edit snapshot evidence. A late snapshot reconstructed after edits is invalid. If overlap makes ownership ambiguous, preserve the baseline and constrain the change to separable hunks; ask only when a destructive choice is unavoidable.

A quarantine successor instead begins with a typed recovery baseline before any new recovery edit. It binds the exact manifest and predecessor digest, repeats the gate-derived request and acceptance without change, captures the current branch, `HEAD`, index, worktree, and untracked hashes, and distinguishes pre-existing user work from inherited agent residue. It adopts that residue truthfully; it does not reconstruct a fictional pre-edit snapshot. Quarantine clears all predecessor candidate, review, verification, and commit context, so the successor must complete every state from design through closure with fresh evidence.

Read open project issues and relevant client-error reports when the request concerns live interact behavior. For GitHub repository metadata, issues, pull requests, and releases, prefer the authenticated `gh` CLI. Treat `gh` API authentication, Git transport authentication, and app-connector authorization as independent states; never report one surface's failure as “GitHub is disconnected.” Before falling back, name the exact surface, bounded failure reason, and attempted capability. Never read or print tokens. Use unauthenticated web only as a public-read fallback, and use an app connector only for a capability the CLI cannot supply. This access order grants no authority to push, publish, release, close, comment, or otherwise mutate an external resource. Treat cross-project client logs as private: inspect only the current project's records, minimize excerpts, and redact paths, prompts, tokens, and user content from reports.

### 2. DESIGNED

Before code, add a design checkpoint to the iteration ledger:

- chosen interpretation and explicit non-goals;
- affected source-of-truth modules and interfaces;
- invariants, edge cases, trust boundaries, and expected failure behavior;
- the smallest test that proves each acceptance item;
- external seams, required negative controls, likely cost, and the visual verification route;
- compatibility decision: cut over cleanly or preserve behavior for a stated reason.

New public classes or models require the coding skill's class-design check before their declaration. A design review performed after implementation is not pre-code evidence.

Order the design and implementation by acceptance dependency: deliver the user's primary architectural or product outcome first, then the correctness, safety, and delivery work required to make that outcome real. Optional polish and unrelated cleanup remain outside the active candidate; they cannot consume the delivery path before the primary outcome or keep an otherwise complete lineage open.

### 3. RED

A bug fix requires a minimal reproducing test before the fix. Run it against the baseline and record the exact command, environment, exclusions, failing assertion, and trailing summary in the ledger. A new feature requires executable acceptance coverage before or with implementation; record why an existing parametrized test could not cover it before adding another test.

A mock of the suspected subsystem is not reproduction. At least one integration test must cross each external dependency used by the changed path.

### 4. IMPLEMENTED

Implement only the designed scope. Preserve baseline-owned changes. Use typed boundaries, existing project abstractions, and the smallest general solution. Do not add compatibility shims in this pre-1.0 project unless the design checkpoint names a real consumer that requires one.

For an external session, model, service, process, or GUI seam, run both controls:

- a positive control through the real seam;
- a negative control that deliberately makes the seam unavailable, invalid, stale, or unauthorized and proves the expected fallback or error.

A happy-path mock plus a green unit suite is false-green evidence for integration behavior.

### 5. CANDIDATE_FROZEN

Stage only iteration-owned paths explicitly. Record the candidate tree from `git write-tree` and the exact diff reviewed. All subsequent reviewers and verification commands must target this same tree. A quarantine successor freezes the full adopted product and governance tree; no predecessor candidate or approval survives into it.

Before `COMMITTED`, bind the active candidate to both the current index tree and its staged-diff hash. After `COMMITTED`, require a clean index and bind through the recorded commit and `HEAD` tree; never compare the clean post-commit diff with the historical staged-diff hash. If any source, test, generated file, configuration, or staged hunk changes before commit, the candidate hash is obsolete. Freeze a new candidate and rerun every affected gate. Reviews against different diffs cannot be combined into one approval.

### 6. REVIEWED

Use independent generic workers when they add real coverage, and give each the frozen tree hash and identical acceptance list. Before candidate approval, one independent structural review must inspect the whole frozen diff for boundary coherence, duplication, misplaced responsibility, and consistency with the design; narrower specialist reviews supplement that whole-diff review rather than fragmenting it. Required gates are determined by the change, not by a standing ceremony:

- code changes: independent functional verification and diff review;
- public API or architecture changes: boundary and compatibility review;
- user-facing behavior: product acceptance plus live visual or interaction verification;
- security or privacy boundaries: threat and secret review;
- performance claims: a measured realistic-scale review.

A reviewer must report what it ran or inspected, exact exclusions, and findings tied to the candidate hash. Every `REVIEWED` command row must exit zero; encode an expected-negative control as an outer assertion that verifies the inner failure and succeeds, retaining the inner result in the summary. An approved reviewer has no findings. When every reviewer is approved, the candidate may advance to `VERIFIED`; before verification, newly executed evidence that disproves the frozen candidate may instead append one typed nonzero `RED` directly. A second `REVIEWED` event for the same candidate is invalid. A `changes_requested` or `rejected` reviewer has typed findings; any such disposition makes the candidate-bound `REVIEWED` event a structurally valid current terminal under both `verify-ledger` and `validate-append`, with `RED` as its sole next state. Prospective validation must accept a nonapproved review or a direct post-approval `RED` without requiring a future event to exist. The candidate remains bound until the accepted typed nonzero `RED` clears it; `IMPLEMENTED`, a fresh `CANDIDATE_FROZEN`, and fresh review then follow. Only a finding tied to an acceptance item, invariant, or executable regression blocks the candidate; optional polish is recorded outside the active lineage and cannot force another review cycle. A review that trusts another worker's pass count, checks only the implementation narrative, silently uses a smaller scope, or substitutes several partial reviews for the whole-diff structural review is invalid. Quarantine requires an independent validator to reproduce the exact predecessor failure and inspect the manifest, trusted-prefix binding, successor acceptance, and full frozen candidate.

### 7. VERIFIED

Append one verification manifest to the iteration ledger. For every command record the candidate tree hash, working directory, relevant environment, exact command, explicit include/exclude set, exit code, and literal trailing summary. Record skipped tests as exclusions, never as passes. A quarantine successor reruns every applicable gate; predecessor verification is historical context, not corroboration.

Test totals are comparable only when commands and exclusions are identical. Different scopes remain separate manifest rows and cannot corroborate one another by count.

For long-lived consumers, verify delivery on the instance the user actually runs. Source changes, a reinstall, or a passing suite do not prove that an already-running MCP server or extension host loaded the change.

### 8. COMMITTED

This repository uses relaxed git mode: direct commits to `main`, conventional commit messages, no AI or co-author trailers, and explicit staging. Do not create a feature branch unless the user requests one or remote policy requires it.

Run the tracked pre-commit hook from bytes proven identical to the candidate index. Read quarantine manifests and commit inputs from that same index; unstaged or worktree-only evidence has no authority. If the hook changes the index, freeze a new candidate and rerun affected reviews and verification. After commit, record the commit SHA and assert that `git rev-parse HEAD^{tree}` equals the verified candidate tree. A mismatch returns the active epoch to `CANDIDATE_FROZEN`. Historical commits from superseded epochs must still resolve to their recorded trees but are not required to equal current `HEAD`.

Do not push, release, publish, deploy, close external issues, or send messages without authorization for that external action.

### 9. CLOSED

The main thread checks every acceptance item against evidence, confirms no owned process or window remains unintentionally live, and records remaining blockers that genuinely require user input or external state.

Every participating agent appends a dated entry containing the iteration id to its canonical memory file. Code changes always require `developer.md`; every iteration requires `pm.md`; prompt changes require `librarian.md`. The final epoch reconciles the union of participants and required memories from every superseded epoch; a quarantine successor also includes every participant derived from the predecessor's trusted prefix. Before closing, verify each expected file exists, is non-empty, and contains the successor iteration id. Missing or untouched memory returns the work to the responsible participant.

Close only when all acceptance items are satisfied or explicitly blocked, no user-visible work is claimed complete with an open visual gate, the verified tree equals the committed tree, and no user-visible async work remains. An earlier `CLOSED` followed by `SUPERSEDED` is an invalidated audit record, not the terminal state. Continue the current iteration while an acceptance item is executable now; do not continue into unrelated improvements after closure.

## Visual acceptance

Any visual or interaction claim requires evidence from the rendered surface. Use this fallback chain in order:

- the installed interact MCP tools against an isolated target;
- the project's nested display backend with Xvfb or Xephyr and a captured frame;
- a browser or webview debug target reached through Playwright or the Chrome DevTools Protocol, with a screenshot and exercised control;
- a deterministic render artifact plus accessibility or DOM assertions, only when no live pixel route exists.

Record the attempted route and failure before falling back. A screenshot of the launcher, button, or empty shell does not verify the content. If no route yields the pixels or interaction required by acceptance, leave the pixel gate `OPEN`, do not commit or present the visual work as done, and state the blocking environment fact.

Never operate the user's active desktop. Use an isolated display, test profile, or background target. Close or explicitly hand off every spawned display, browser, server, and editor instance.

## Cost and external services

Never equate an existing subscription, authenticated session, bundled quota, trial, or cached credential with zero marginal cost. Before claiming a session-backed path avoids API expense, establish from current account or product evidence whether usage is included, metered, rate-limited, or prohibited by terms. Use the narrow claim supported by evidence, such as avoiding separate API-key billing, and record uncertainty.

Do not run paid model, benchmark, or scoring calls for facts already present in bundled published data. A missing published value still requires explicit budget approval before paid measurement. One approved run does not authorize retries with a changed model, sample count, or provider.

Do not read credential stores, keyrings, extension SecretStorage, `.env` values, or unrelated process environments. Discover configured providers only through the product's supported public interface.

## Provider-independent secret gate

Before every commit, inspect the staged diff for credential-like values, private keys, personal absolute paths, and configured confidential terms. Redact detected values in all output; report only file, line, and secret class. Never echo the matching line.

The tracked `.githooks/pre-commit` is the provider-independent enforcement point. Run its staged scanner and ledger verifier before every commit and record their exact command and result in the verification manifest. Provider-specific hooks are early feedback only and cannot satisfy this gate.

## Project verification

- Unit baseline: `uv run pytest tests/ -q --tb=short`.
- VLM or detection changes require the integration-marked real-seam suite and inspection of produced annotations.
- VS Code extension changes require compile, package, install into an isolated profile, restart of that extension host, and visual verification of rendered content.
- Webview data must cross a typed JSON boundary and be rendered without interpolating untrusted content into HTML or executable attributes.
- Output artifacts stay under the existing `out/vscode/` or `out/tests/` category structure and are never committed.
- Version bumps are batched only when the user asks to release. Keep Python and extension versions synchronized through the project versioning command; CI owns tags.
