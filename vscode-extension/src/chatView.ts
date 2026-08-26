/** The Chat view — the side-bar surface you TALK to an agent from.
 *
 *  The tree lists what is running; the conversation tab shows what happened. Both are windows.
 *  This one is a conversation: it sits under the agent list in the same side-bar container, shows
 *  the selected agent's transcript, and has a composer that sends a message back. The agent
 *  resumes its own session, so it answers with everything it has already done still in context.
 *
 *  Sending shells out to `interact agents send` rather than reimplementing delivery: the CLI and
 *  the MCP tool share one set of refusals (an unknown run, one of your own editor sessions, a
 *  provider that cannot resume), and this must not drift from them.
 */
import * as fs from "fs";
import * as vscode from "vscode";

import { AgentRun, activityOf, readAgentRuns } from "./agents";
import { chatFiles } from "./chatFiles";
import { CHAT_COMMANDS } from "./chatCommands";
import { agentLabel, conversationTitle, roleOf } from "./roster";
import { agentDocument, agentView } from "./agentPanel";
import { DIM_FOREGROUND } from "./themeTokens";
import { modelChosenFor } from "./agentModels";
import { companyOf, definitionFile, readOrg } from "./org";
import { teamSpend } from "./teamSpend";
import { scopeStore } from "./scopeStore";
import { interactCli } from "./interactCli";
import { describeMode, knownModes, type PermissionMode } from "./permissionModes";
import { chatDocument, isAwaitingReply, transcriptFragment } from "./conversationFormat";
import { sessionTabs } from "./sessionTabs";
import { IO_SCHEME, ioTarget } from "./ioDocument";
import { agentsDir } from "./paths";

export class ChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewId = "interactAgents.chat";

  /** Set while a conversation is open. The roster views' `when` clauses watch it, so the column
   *  belongs to whichever of the two you are actually using. */
  public static readonly IN_CONVERSATION = "interact.inConversation";

  /** Hand the column back to the roster. */
  public static leaveConversation(): void {
    void vscode.commands.executeCommand(ChatViewProvider.IN_CONVERSATION_CLEAR);
  }

  /** Leave whatever depth you are at and return to the team.
   *
   *  The command used to only flip a context key and re-reveal the Team tab. That worked when the
   *  key HID the roster view — but the roster moved to the big panel and the key now gates
   *  nothing, so "back" became a button that did nothing at every depth, with no way out of a
   *  conversation except clicking a different agent. State has to be cleared and the panel
   *  repainted; a context key is not navigation.
   */
  /** Repaint the agent depth if it is what you are looking at.
   *
   *  Choosing a model wrote the file and toasted, but the open panel kept showing the old one until
   *  you navigated away and back — which defeats the reason the override is rendered at all: a
   *  choice you cannot see is one you forget you made. */
  public repaintAgent(agent: string): void {
    if (this.agentId === agent) this.render();
  }

  public backToTeam(): void {
    this.agentId = null;
    this.runId = undefined;
    this.rendered = undefined;
    this.render();
  }

  private static readonly IN_CONVERSATION_CLEAR = "interact.agents.backToTeam";

  private view: vscode.WebviewView | undefined;
  private runId: string | undefined;
  private watcher: fs.FSWatcher | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly log: vscode.OutputChannel) {}

  /** Point the panel at an agent — what clicking a row in the list, or a body in the workplace,
   *  does.
   *
   *  Reveals the CONTAINER first when the view has never resolved. `view?.show()` is a no-op
   *  until VS Code has instantiated the webview, so clicking somebody in the team floor with the
   *  panel closed did nothing at all, silently — the worst kind of dead control, because it looks
   *  like the click missed.
   */
  public show(runId: string): void {
    this.agentId = null;  // opening a conversation leaves the agent depth
    void this.reveal(runId);
  }

  /** The middle depth: an agent, its identity, and the tasks it was given.
   *
   *  "on the sidepanel, we should be able to view what TASKS an agent was given, and then proceed
   *  to view the conversation we want" — this is that view, and the place the two things you
   *  MANAGE about an agent live: its definition file and the model it runs on.
   */
  public showAgent(agent: string): void {
    this.agentId = agent;
    this.runId = undefined;
    this.rendered = undefined;
    void this.revealAgent();
  }

  private async revealAgent(): Promise<void> {
    this.render();
    await vscode.commands.executeCommand("setContext", ChatViewProvider.IN_CONVERSATION, true);
    if (this.view) { void this.view.show?.(true); }
    await vscode.commands.executeCommand("interactAgents.chat.focus");
    this.render();
  }

  /** Awaited, because the Chat view now carries `when: interact.inConversation` — it does not
   *  exist to focus until that key is actually set, and `setContext` is asynchronous. Firing both
   *  and hoping is how a click lands on nothing. */
  private async reveal(runId: string): Promise<void> {
    this.runId = runId;
    this.render();
    // "The chat page shouldn't be small... i'm having to close the menus for team and agent."
    // The roster views' `when` clauses watch this key, so opening a conversation gives it the whole
    // column with nobody collapsing anything by hand.
    //
    // FIRST, and unconditionally. This lived inside the `!this.view` branch below and was therefore
    // dead in every normal open: the Chat webview has no `when` of its own, so it resolves as soon
    // as the container is visible and `this.view` is already truthy the first time anyone clicks a
    // row. A visual-critic round reproduced it live in both themes — the Team list simply never
    // stepped aside.
    await vscode.commands.executeCommand("setContext", ChatViewProvider.IN_CONVERSATION, true);
    if (this.view) {
      // Reveal only on an explicit pick, so following a live run never steals the side bar.
      void this.view.show?.(true);
      return;
    }
    await vscode.commands.executeCommand("interactAgents.chat.focus");
  }

  public resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    // This view now carries `when: interact.inConversation`, so VS Code DISPOSES it every time the
    // clause goes false — and a disposed webview whose reference we kept throws on the next write.
    // That made the SECOND conversation you opened blank the whole sidebar with no visible way
    // back: `Error: Webview is disposed` out of render(), sidebar chrome and nothing in it.
    // Forget it here and the next show() resolves a fresh one. The roster view always guarded this;
    // this file never needed to until a `when` clause made it disposable too.
    // Paint when it actually becomes visible. render() now refuses to write to a hidden view, and
    // a `when`-gated view can resolve a moment before VS Code shows it — without this the first
    // conversation of a session could resolve to an empty panel.
    view.onDidChangeVisibility(() => { if (view.visible) this.render(); });
    view.onDidDispose(() => {
      if (this.view === view) this.view = undefined;
      this.rendered = undefined;  // the next view starts empty; a stale id would skip the paint
    });
    // Asked once, not per render: the answer only changes when the CLI is upgraded, and a panel
    // that shells out on every repaint is a panel that stutters while an agent is working. The
    // memoisation lives in knownModes(), shared with the spawn picker and the workspace default —
    // this was three shell-outs for one answer, with three different error handlings.
    void knownModes().then((modes) => { this.modes = modes; });
    // `enableCommandUris` is what lets a file link actually open the file: without it VS Code
    // silently drops the command: href, which looks exactly like a dead button.
    view.webview.options = { enableScripts: true, enableCommandUris: true };
    view.webview.onDidReceiveMessage((msg) => {
      if (msg?.type === "send" && typeof msg.text === "string") void this.send(msg.text);
      if (msg?.type === "back") { this.agentId = null; void ChatViewProvider.leaveConversation(); }
      // The empty state's door: an empty panel must lead somewhere, not describe a missing list.
      if (msg?.type === "openTeam") void vscode.commands.executeCommand("interact.agents.team");
      // The two things you MANAGE about an agent, from the depth where the agent IS the subject.
      if (msg?.type === "agentAction" && typeof msg.agent === "string") {
        if (msg.action === "model") void vscode.commands.executeCommand("interact.agents.model", msg.agent);
        if (msg.action === "definition" && typeof msg.path === "string") {
          void vscode.window.showTextDocument(vscode.Uri.file(msg.path));
        }
      }
      // Walking UP the tree: the errand that produced this answer.
      if (msg?.type === "openRun" && typeof msg.runId === "string") this.show(msg.runId);
      // The whole input/output of one tool call, in its own read-only tab — the Claude Code
      // gesture. A stamped call is served from the raw stream by the vendor's tool id; an
      // unstamped one (records predating the stamping) serves the stored text the webview
      // handed over. The id and text are opaque data — a hostile id can only fail to match.
      if (msg?.type === "io" && typeof msg.toolId === "string"
          && (msg.side === "in" || msg.side === "out") && this.runId) {
        const path = ioTarget(this.runId, msg.toolId, msg.side,
          String(msg.tool ?? "tool"), typeof msg.text === "string" ? msg.text : "");
        if (path) {
          const uri = vscode.Uri.from({ scheme: IO_SCHEME, path });
          void vscode.window.showTextDocument(uri, { preview: true });
        }
      }
      if (msg?.type === "open" && typeof msg.path === "string") void this.open(msg.path);
      // A command from the slash menu. Checked against the declared list rather than executed as
      // given: the webview renders agent output, so anything arriving from it is untrusted, and
      // running an arbitrary command id because a message said so would be a real hole.
      if (msg?.type === "pickFile") void this.mentionFile();
      if (msg?.type === "command" && typeof msg.command === "string") {
        const known = CHAT_COMMANDS.find((c) => c.command === msg.command);
        if (!known) return;
        const run = this.run();
        if (known.needsAgent && !run) {
          void vscode.window.showInformationMessage(`${known.slash} needs an agent open.`);
          return;
        }
        void vscode.commands.executeCommand(known.command, run ? { run } : undefined);
      }
    });
    view.onDidDispose(() => this.stopWatching());
    this.watch();
    this.render();
  }

  private run(): AgentRun | undefined {
    // The registry first, then the scope store's merged view — which is where your OWN
    // discovered sessions live. Without the fallback a "your session" row opened onto the
    // empty hint: the id was real, the lookup just never asked the list that holds it.
    return readAgentRuns().find((r) => r.run_id === this.runId)
      ?? scopeStore()?.runs().find((r) => r.run_id === this.runId);
  }

  /** Which run the live document was built for. A different agent needs a new document; the SAME
   *  agent going on working needs only its transcript swapped. */
  private rendered: string | undefined;
  /** When set, the panel is at the AGENT depth: who this is, and the tasks it was given. The
   *  conversation is one level deeper. */
  private agentId: string | null = null;
  /** The autonomy levels this machine's CLI offers, read once — turning an id recorded on a run
   *  ("acceptEdits") into the words somebody chose it by ("May edit files"). */
  private modes: PermissionMode[] = [];

  /** The agent depth. Identity from the company file, tasks from the registry. */
  private renderAgent(agent: string): void {
    if (!this.view) return;
    const org = readOrg();
    const declared = org?.agents.find((a) => a.name === agent);
    // Resolved identity, NOT the literal field. A definition-less run's `agent` is null and its id
    // ("main", the coordinator) exists only through roleOf's fallback — so filtering on the raw
    // field showed "No tasks yet" for the coordinator while five of its errands were visibly
    // failing in the room. That was precisely the case this whole change was written for.
    const company = companyOf(readOrg()) ?? undefined;
    const tasks = readAgentRuns().filter((r) => roleOf(r as never, company).id === agent);
    const body = agentView(
      {
        id: agent,
        title: declared?.title ?? null,
        department: declared?.department ?? null,
        model: modelChosenFor(agent),
        declaredModel: declared?.model ?? null,
        // Resolved, not the raw relative string the company file records — an unresolved path
        // opens nothing and the chip would look live while doing nothing.
        definitionPath: definitionFile(agent, org)
          ?? tasks.find((t) => t.definition_path)?.definition_path ?? null,
      },
      tasks as never[],
      "N",
    );
    const nonce = Math.random().toString(36).slice(2) + Date.now().toString(36);
    this.view.webview.html = agentDocument(nonce, body, DIM_FOREGROUND);
    this.rendered = undefined;  // the next conversation must repaint, not be skipped as unchanged
  }

  private render(): void {
    // `visible` as well as present: a view can be resolved and hidden, and writing to one VS Code
    // has already torn down throws rather than no-ops.
    if (!this.view?.visible) return;
    if (this.agentId) { this.renderAgent(this.agentId); return; }
    const current = this.run();
    if (current && this.rendered === current.run_id) {
      // Same agent, more to say: patch the transcript and leave the rest of the view alone.
      const turns = activityOf(current, 300);
      void this.view.webview.postMessage({
        type: "transcript",
        html: transcriptFragment({
          turns,
          name: current.name,
          awaitingReply: isAwaitingReply(turns),
        }),
      });
      return;
    }
    this.rendered = current?.run_id;
    const run = this.run();
    const turns = run ? activityOf(run, 300) : [];
    // Who sent this one on its errand. Resolved here (the renderer stays import-free) and named by
    // what the caller is DOING, so "↑ parent" reads as a place rather than an id.
    const all = readAgentRuns();
    const mine = all.find((r) => r.run_id === this.runId);
    const parentRun = mine?.parent_run_id ? all.find((r) => r.run_id === mine.parent_run_id) : undefined;
    this.view.webview.html = chatDocument({
      parent: parentRun ? { runId: parentRun.run_id, title: conversationTitle(parentRun as never) } : null,
      // A fresh nonce per render: the CSP admits only scripts carrying it, so nothing that
      // arrives in an agent's output can execute even if the escaping were ever wrong.
      nonce: Math.random().toString(36).slice(2) + Date.now().toString(36),
      // The slash menu's entries. Omitted here for a whole release: the "/" button rendered, was
      // enabled, and opened an empty list in every state, because this one argument was optional
      // and never passed. It is required now, so the compiler refuses the omission.
      commands: CHAT_COMMANDS,
      turns,
      name: run?.name,
      status: run?.status,
      // One of your own sessions: shown in full, steered in its own window — the composer
      // says so instead of offering a Send the CLI would refuse.
      readOnly: run?.status === "foreign",
      // Everyone on this errand: the entry agent first (the way back), then whoever it put to
      // work, then their own helpers. Live dots say who is still going while you read someone
      // else's transcript.
      tabs: run
        ? sessionTabs(all as never[], run.run_id,
            (r) => agentLabel(r as never, companyOf(readOrg()) ?? undefined))
        : [],
      awaitingReply: isAwaitingReply(turns),
      run: run
        ? ({ ...run, permission: describeMode(run.permission_mode, this.modes) } as never)
        : (run as never),
      // What the whole TEAM is costing, not only the agent being read. Imported and then never
      // called for a whole commit: the row rendered in the preview fixture, which passes its own
      // spend, so every screenshot of it was real and meant nothing about the panel.
      spend: teamSpend(scopeStore()?.runs() ?? readAgentRuns(), run?.run_id),
      files: run ? chatFiles(run, agentsDir(), fs.existsSync) : [],
      sentBy: run?.parent_run_id
        ? readAgentRuns().find((r) => r.run_id === run.parent_run_id)?.name ?? null
        : null,
    });
  }

  /** Offer a workspace file and hand its path back to the composer.
   *
   *  The webview cannot enumerate the workspace, so "@" comes here. Paths are relative to the
   *  folder, because that is what an agent working in that folder can actually open — an absolute
   *  path from this machine is noise in a brief.
   */
  private async mentionFile(): Promise<void> {
    const found = await vscode.workspace.findFiles("**/*", "**/{node_modules,.git,out,dist}/**", 2000);
    if (found.length === 0) {
      void vscode.window.showInformationMessage("No files in this workspace to mention.");
      return;
    }
    const picked = await vscode.window.showQuickPick(
      found.map((uri) => ({ label: vscode.workspace.asRelativePath(uri), uri })),
      { title: "Mention a file", matchOnDescription: true },
    );
    if (picked) this.view?.webview.postMessage({ type: "insert", text: `@${picked.label} ` });
  }

  /** Open a file in an editor — a webview cannot, so it asks us to.
   *
   *  A failure is SHOWN, not just logged: a button that silently does nothing is the defect, and
   *  the log is somewhere nobody looks until they already suspect one.
   */
  private async open(target: string): Promise<void> {
    try {
      const uri = vscode.Uri.file(target);
      // "when we click on it it opens the code DIFF in the file." For a source file with pending
      // changes, the git extension's own view IS that diff — the same one its gutter opens. It
      // no-ops or throws for an unchanged or untracked file, so the plain editor is the fallback,
      // and an image never goes near it (VS Code renders it in its own viewer).
      if (!/\.(png|jpe?g|gif|webp)$/i.test(target)) {
        try {
          await vscode.commands.executeCommand("git.openChange", uri);
          return;
        } catch {
          /* not in a repo, not modified, or no git extension — the file itself is still right */
        }
      }
      await vscode.commands.executeCommand("vscode.open", uri, { preview: true });
    } catch (err) {
      this.log.appendLine(`could not open ${target}: ${err}`);
      void vscode.window.showErrorMessage(`Interact: could not open ${target} — ${err}`);
    }
  }

  private async send(text: string): Promise<void> {
    const run = this.run();
    if (!run) return;
    const { error, stdout } = await interactCli(["agents", "send", run.run_id, text]);
    const failed = Boolean(error) || stdout.trim().startsWith("ERROR");
    // Told either way. The webview empties the box optimistically and keeps the text until this
    // arrives — without the answer it would hold a message forever, and a failed send used to
    // destroy what you wrote.
    void this.view?.webview.postMessage({ type: "sent", ok: !failed });
    if (failed) {
      void vscode.window.showErrorMessage(
        `Could not reach ${run.name} — ${error || stdout.trim()}`);
      return;
    }
    this.render(); // recorded on both sides, so it is already in the transcript
  }

  /** Follow the registry so an agent opened mid-flight keeps updating as it works. */
  private watch(): void {
    this.stopWatching();
    try {
      this.watcher = fs.watch(agentsDir(), () => {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.render(), 250); // coalesce a burst of writes
      });
    } catch (err) {
      this.log.appendLine(`chat view is not following changes: ${err}`);
    }
  }

  private stopWatching(): void {
    clearTimeout(this.timer);
    this.watcher?.close();
    this.watcher = undefined;
  }
}
