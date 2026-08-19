/** The full-size chat page: an agent's conversation, in the editor area, that you can REPLY from.
 *
 *  This was a read-only transcript with `enableScripts: false`. So the BIG surface could not chat,
 *  and the only place you could actually say anything to an agent was a webview crammed into a
 *  ~292px sidebar. "The chat page shouldn't be small" is that, exactly: the roomy one was inert
 *  and the live one had no room.
 *
 *  It now renders the SAME document as the sidebar (`chatDocument`), so the two surfaces cannot
 *  drift into two different chats, and it accepts the same message contract (`chatAction`) rather
 *  than growing a second, weaker copy of the untrusted-input rules.
 *
 *  One panel, reused: clicking another agent retargets it instead of stacking editor tabs.
 */
import * as fs from "fs";
import * as vscode from "vscode";

import { readAgentActivity, readAgentRuns } from "./agents";
import { CHAT_COMMANDS } from "./chatCommands";
import { chatAction } from "./chatMessage";
import { chatFiles } from "./chatFiles";
import { chatDocument, isAwaitingReply } from "./conversationFormat";
import { describeMode, knownModes, type PermissionMode } from "./permissionModes";
import { interactCli } from "./interactCli";
import { claimColumn, nextColumn, releaseColumn } from "./panelColumn";
import { agentsDir } from "./paths";
import { scopeStore } from "./scopeStore";
import { teamSpend } from "./teamSpend";

export class ConversationPanel {
  private static current: ConversationPanel | undefined;
  private watcher: fs.FSWatcher | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private modes: PermissionMode[] = [];

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private runId: string,
  ) {
    this.panel.onDidDispose(() => this.dispose());
    claimColumn("conversation", this.panel.viewColumn);
    this.panel.webview.onDidReceiveMessage((msg) => this.receive(msg));
    void knownModes().then((modes) => { this.modes = modes; this.render(); });
    this.watch();
    this.render();
  }

  static show(runId: string): void {
    if (ConversationPanel.current) {
      ConversationPanel.current.runId = runId;
      ConversationPanel.current.panel.reveal(ConversationPanel.current.panel.viewColumn);
      ConversationPanel.current.render();
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      "interact.conversation",
      "Agent conversation",
      nextColumn() as vscode.ViewColumn,
      // Scripts ON, unlike before: this is a chat, and a chat you cannot type into is a
      // transcript. The CSP still admits only the per-render nonce, and everything an agent
      // wrote is escaped before it reaches the document.
      { enableScripts: true, retainContextWhenHidden: true },
    );
    ConversationPanel.current = new ConversationPanel(panel, runId);
  }

  /** Point the open page at another agent — what clicking a row, or a body in the team, does. */
  static reveal(runId: string): void {
    ConversationPanel.show(runId);
  }

  private receive(message: unknown): void {
    const action = chatAction(message, CHAT_COMMANDS);
    if (!action) return;
    if (action.kind === "send") return void this.send(action.text);
    if (action.kind === "command") return void vscode.commands.executeCommand(action.command);
    if (action.kind === "open") {
      return void vscode.window.showTextDocument(vscode.Uri.file(action.path), { preview: true });
    }
    if (action.kind === "pickFile") return void this.mentionFile();
  }

  private async send(text: string): Promise<void> {
    const run = readAgentRuns().find((r) => r.run_id === this.runId);
    if (!run) return;
    const { error, stdout } = await interactCli(["agents", "send", run.run_id, text]);
    const failed = Boolean(error) || stdout.trim().startsWith("ERROR");
    // Same contract as the sidebar: the webview keeps your text until it hears back, so a failed
    // send never destroys what you wrote.
    void this.panel.webview.postMessage({ type: "sent", ok: !failed });
    if (failed) {
      void vscode.window.showErrorMessage(
        `Could not reach ${run.name} — ${error || stdout.trim()}`);
      return;
    }
    this.render(); // recorded on both sides, so it is already in the transcript
  }

  /** Offer a workspace file and hand its path to the composer, as the sidebar does. */
  private async mentionFile(): Promise<void> {
    const found = await vscode.workspace.findFiles(
      "**/*", "**/{node_modules,.git,out,dist}/**", 2000);
    if (!found.length) return;
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const picked = await vscode.window.showQuickPick(
      found.map((f) => (folder ? f.fsPath.replace(`${folder}/`, "") : f.fsPath)).sort(),
      { title: "Mention a file", placeHolder: "its path goes into your message" },
    );
    if (picked) void this.panel.webview.postMessage({ type: "mention", path: picked });
  }

  private watch(): void {
    try {
      this.watcher = fs.watch(agentsDir(), () => {
        if (this.timer) clearTimeout(this.timer);
        this.timer = setTimeout(() => this.render(), 300);
      });
      this.watcher.on("error", () => {});
    } catch {
      /* unwatchable → the page is simply static */
    }
  }

  private dispose(): void {
    this.watcher?.close();
    if (this.timer) clearTimeout(this.timer);
    releaseColumn("conversation");
    ConversationPanel.current = undefined;
  }

  private render(): void {
    const run = readAgentRuns().find((r) => r.run_id === this.runId);
    const turns = readAgentActivity(this.runId, 500);
    this.panel.title = run ? `${run.name} — chat` : "Agent chat";
    this.panel.webview.html = chatDocument({
      nonce: Math.random().toString(36).slice(2) + Date.now().toString(36),
      turns,
      name: run?.name,
      status: run?.status,
      awaitingReply: isAwaitingReply(turns),
      commands: CHAT_COMMANDS,
      run: run
        ? ({ ...run, permission: describeMode(run.permission_mode, this.modes) } as never)
        : (run as never),
      spend: teamSpend(scopeStore()?.runs() ?? readAgentRuns(), run?.run_id),
      files: run ? chatFiles(run, agentsDir(), fs.existsSync) : [],
      sentBy: run?.parent_run_id
        ? readAgentRuns().find((r) => r.run_id === run.parent_run_id)?.name ?? null
        : null,
    });
  }
}
