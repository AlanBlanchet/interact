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
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

import { AgentRun, readAgentActivity, readAgentRuns } from "./agents";
import { chatFiles } from "./chatFiles";
import { ChatFile, chatDocument, isAwaitingReply, transcriptFragment } from "./conversationFormat";
import { agentsDir } from "./paths";

export class ChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewId = "interactAgents.chat";

  private view: vscode.WebviewView | undefined;
  private runId: string | undefined;
  private watcher: fs.FSWatcher | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly log: vscode.OutputChannel) {}

  /** Point the panel at an agent — what clicking a row in the list does. */
  public show(runId: string): void {
    this.runId = runId;
    this.render();
    // Reveal only on an explicit pick, so following a live run never steals the side bar.
    void this.view?.show?.(true);
  }

  public resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    // `enableCommandUris` is what lets a file link actually open the file: without it VS Code
    // silently drops the command: href, which looks exactly like a dead button.
    view.webview.options = { enableScripts: true, enableCommandUris: true };
    view.webview.onDidReceiveMessage((msg) => {
      if (msg?.type === "send" && typeof msg.text === "string") void this.send(msg.text);
      if (msg?.type === "open" && typeof msg.path === "string") void this.open(msg.path);
    });
    view.onDidDispose(() => this.stopWatching());
    this.watch();
    this.render();
  }

  private run(): AgentRun | undefined {
    return readAgentRuns().find((r) => r.run_id === this.runId);
  }

  /** Which run the live document was built for. A different agent needs a new document; the SAME
   *  agent going on working needs only its transcript swapped. */
  private rendered: string | undefined;

  private render(): void {
    if (!this.view) return;
    const current = this.run();
    if (current && this.rendered === current.run_id) {
      // Same agent, more to say: patch the transcript and leave the rest of the view alone.
      const turns = readAgentActivity(current.run_id, 300);
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
    const turns = run ? readAgentActivity(run.run_id, 300) : [];
    this.view.webview.html = chatDocument({
      // A fresh nonce per render: the CSP admits only scripts carrying it, so nothing that
      // arrives in an agent's output can execute even if the escaping were ever wrong.
      nonce: Math.random().toString(36).slice(2) + Date.now().toString(36),
      turns,
      name: run?.name,
      status: run?.status,
      awaitingReply: isAwaitingReply(turns),
      run: run as never,
      files: run ? chatFiles(run, agentsDir(), os.homedir(), fs.existsSync) : [],
      sentBy: run?.parent_run_id
        ? readAgentRuns().find((r) => r.run_id === run.parent_run_id)?.name ?? null
        : null,
    });
  }

  /** Open a file in an editor — a webview cannot, so it asks us to.
   *
   *  A failure is SHOWN, not just logged: a button that silently does nothing is the defect, and
   *  the log is somewhere nobody looks until they already suspect one.
   */
  private async open(target: string): Promise<void> {
    try {
      const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(target));
      await vscode.window.showTextDocument(doc, { preview: true, preserveFocus: false });
    } catch (err) {
      this.log.appendLine(`could not open ${target}: ${err}`);
      void vscode.window.showErrorMessage(`Interact: could not open ${target} — ${err}`);
    }
  }

  private async send(text: string): Promise<void> {
    const run = this.run();
    if (!run) return;
    const { execFile } = await import("child_process");
    execFile("interact", ["agents", "send", run.run_id, text], (err, stdout, stderr) => {
      const said = (stdout || stderr || "").trim();
      if (err || said.startsWith("ERROR")) {
        vscode.window.showErrorMessage(said || `Could not reach ${run.name}.`);
        return;
      }
      this.render(); // the message is recorded on both sides, so it is already in the transcript
    });
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
