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

import { AgentRun, readAgentActivity, readAgentRuns } from "./agents";
import { chatDocument } from "./conversationFormat";
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
    view.webview.options = { enableScripts: true };
    view.webview.onDidReceiveMessage((msg) => {
      if (msg?.type === "send" && typeof msg.text === "string") void this.send(msg.text);
    });
    view.onDidDispose(() => this.stopWatching());
    this.watch();
    this.render();
  }

  private run(): AgentRun | undefined {
    return readAgentRuns().find((r) => r.run_id === this.runId);
  }

  private render(): void {
    if (!this.view) return;
    const run = this.run();
    this.view.webview.html = chatDocument({
      // A fresh nonce per render: the CSP admits only scripts carrying it, so nothing that
      // arrives in an agent's output can execute even if the escaping were ever wrong.
      nonce: Math.random().toString(36).slice(2) + Date.now().toString(36),
      turns: run ? readAgentActivity(run.run_id, 300) : [],
      name: run?.name,
      status: run?.status,
    });
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
