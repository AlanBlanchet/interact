/** The Agent Conversation panel — click an agent, read what it actually did.
 *
 *  The sidebar answers "what is running"; this answers "what happened", as a conversation: the
 *  model's turns, every tool call WITH its arguments, and what each returned. That is the thing
 *  the tree's one-line summaries can never be.
 *
 *  One panel, reused: clicking another agent retargets it rather than stacking editor tabs. It
 *  follows a live run by watching the registry, so an agent you open mid-flight keeps updating.
 */
import * as fs from "fs";
import * as vscode from "vscode";

import { AgentRun, readAgentActivity, readAgentRuns } from "./agents";
import { renderTranscript } from "./conversationFormat";
import { agentsDir } from "./paths";

export class ConversationPanel {
  private static current: ConversationPanel | undefined;
  private watcher: fs.FSWatcher | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private runId: string,
  ) {
    this.panel.onDidDispose(() => this.dispose());
    this.watch();
    this.render();
  }

  static show(runId: string): void {
    const column = vscode.ViewColumn.Beside; // beside your code, like a chat panel
    if (ConversationPanel.current) {
      ConversationPanel.current.runId = runId;
      ConversationPanel.current.panel.reveal(column);
      ConversationPanel.current.render();
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      "interact.conversation",
      "Agent conversation",
      column,
      { enableScripts: false, retainContextWhenHidden: true },
    );
    ConversationPanel.current = new ConversationPanel(panel, runId);
  }

  private watch(): void {
    try {
      this.watcher = fs.watch(agentsDir(), () => {
        if (this.timer) clearTimeout(this.timer);
        this.timer = setTimeout(() => this.render(), 300);
      });
      this.watcher.on("error", () => {});
    } catch {
      /* unwatchable → the panel is simply static */
    }
  }

  private dispose(): void {
    this.watcher?.close();
    if (this.timer) clearTimeout(this.timer);
    ConversationPanel.current = undefined;
  }

  private render(): void {
    const run = readAgentRuns().find((r) => r.run_id === this.runId);
    const turns = readAgentActivity(this.runId, 500);
    this.panel.title = run ? `${run.name} — conversation` : "Agent conversation";
    this.panel.webview.html = this.html(run, renderTranscript(turns));
  }

  private html(run: AgentRun | undefined, body: string): string {
    const esc = (v: string) => v.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[c]!);
    const head = run
      ? `<h1>${esc(run.name)}</h1>
         <p class="meta">${esc(run.status)} · ${esc(run.provider)}${run.model ? ` · ${esc(run.model)}` : ""}
         · ${run.cost_usd == null ? "—" : `~$${run.cost_usd.toFixed(4)}`} <span class="dim">API-equivalent</span></p>
         ${run.task ? `<blockquote class="task">${esc(run.task)}</blockquote>` : ""}`
      : "<h1>Agent conversation</h1>";
    // Scripts are disabled outright (enableScripts:false) — a transcript is read, never driven,
    // and agent output is untrusted text.
    return `<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
<style>
 body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);
      background:var(--vscode-editor-background);padding:16px 22px;line-height:1.5;
      max-width:900px;margin:0 auto}
 h1{font-size:16px;margin:0 0 2px}
 .meta{color:color-mix(in srgb, var(--vscode-descriptionForeground, #9a9a9a) 70%, var(--vscode-editor-foreground, #d4d4d4));font-size:12px;margin:0 0 12px}
 .dim{opacity:.7}
 .task{margin:0 0 18px;padding:8px 12px;border-left:2px solid var(--vscode-focusBorder);
       background:var(--vscode-textBlockQuote-background);font-size:13px}
 .turn{margin:0 0 12px;padding-left:10px;border-left:2px solid transparent}
 .who{font-size:11px;text-transform:uppercase;letter-spacing:.04em;
      color:color-mix(in srgb, var(--vscode-descriptionForeground, #9a9a9a) 70%, var(--vscode-editor-foreground, #d4d4d4));margin-bottom:3px}
 .body{white-space:pre-wrap;word-break:break-word;margin:0;font-family:inherit}
 pre.body,pre.args{font-family:var(--vscode-editor-font-family);font-size:12px;
      background:var(--vscode-textCodeBlock-background);padding:8px 10px;border-radius:4px;
      overflow-x:auto;margin:0;
      /* Args used to clip silently at a sidebar width, hiding the file_path — the one thing the
         reader came for. Wrap instead of cutting. */
      white-space:pre-wrap;word-break:break-word}
 /* Speech, machinery and reasoning must not look alike — that is what makes it a conversation. */
 .turn-text{border-left-color:var(--vscode-charts-blue)}
 .turn-tool{border-left-color:var(--vscode-charts-purple)}
 .turn-tool .who{color:var(--vscode-charts-purple)}
 /* The result carries its CALL's hue and sits indented beneath it, so the pair reads as one
    exchange. Its old border measured 1.16:1 — invisible — and the two looked unrelated. */
 .turn-tool_result.result-of{border-left-color:var(--vscode-charts-purple);
      margin-left:14px;opacity:.92}
 .turn-thinking{border-left-color:var(--vscode-charts-yellow);opacity:.8;font-style:italic}
 .turn-error{border-left-color:var(--vscode-charts-red)}
 .turn-done .who,.turn-started .who{color:var(--vscode-charts-green)}
</style></head><body>${head}${body}</body></html>`;
  }
}
