/** The TEAM view — the workplace you watch your agents work in.
 *
 *  An editor tab, not a side-bar section: a room full of people needs width, and the point is to
 *  leave it open on a second monitor and glance at it. The side bar keeps the list and the chat.
 *
 *  This file is the HOST only — it assembles a `TeamState` from the registry and hands it to the
 *  renderer. The drawing lives in `webview/workplace/`, so the visual can be reworked without
 *  touching the data, and the data can be fixed without touching the visual.
 */
import * as fs from "fs";
import * as vscode from "vscode";

import { readAgentActivity, readAgentMessages, readAgentRuns } from "./agents";
import { agentsDir } from "./paths";
import { buildTeam } from "./teamState";
import { renderWorkplace } from "./workplaceView";
import type { TeamState } from "./team";

export class WorkplacePanel {
  private static current: WorkplacePanel | undefined;
  private watcher: fs.FSWatcher | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private readonly log: vscode.OutputChannel,
  ) {
    this.panel.onDidDispose(() => this.dispose());
    // A click in the room aims the side-bar Chat at that agent: the workplace is where you SEE
    // the team, the chat is where you talk to one of them, and this is the seam between.
    this.panel.webview.onDidReceiveMessage((msg) => {
      if (msg?.type === "focus" && typeof msg.runId === "string") {
        void vscode.commands.executeCommand("interact.agents.chat", msg.runId);
      }
    });
    this.watch();
    this.render();
  }

  /** One panel, reused — opening it twice should focus the room, not stack tabs of it. */
  public static show(log: vscode.OutputChannel): void {
    if (WorkplacePanel.current) {
      WorkplacePanel.current.panel.reveal();
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      "interact.workplace",
      "Interact — Team",
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true },
    );
    WorkplacePanel.current = new WorkplacePanel(panel, log);
  }

  /** Everyone in the building right now, placed by what they are doing. */
  private state(): TeamState {
    return buildTeam(
      readAgentRuns() as never,
      // The latest recorded step is what puts a worker in a room; one read per worker, and the
      // panel is refreshed on a debounce, so this stays cheap even with a busy registry.
      (runId) => readAgentActivity(runId, 1)[0],
      Date.now() / 1000,
      readAgentMessages() as never,
    );
  }

  private render(): void {
    try {
      this.panel.webview.html = renderWorkplace(this.state(), nonce());
    } catch (err) {
      this.log.appendLine(`workplace render failed: ${err}`);
      this.panel.webview.html = `<!DOCTYPE html><body>${String(err)}</body>`;
    }
  }

  /** Follow the registry so the room moves as the team works. Short debounce on purpose: this is
   *  meant to be watched, and a second of lag reads as a frozen picture. */
  private watch(): void {
    try {
      this.watcher = fs.watch(agentsDir(), () => {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.render(), 150);
      });
    } catch (err) {
      this.log.appendLine(`workplace is not following changes: ${err}`);
    }
  }

  private dispose(): void {
    clearTimeout(this.timer);
    this.watcher?.close();
    this.watcher = undefined;
    WorkplacePanel.current = undefined;
  }
}

/** A fresh nonce per render: the CSP admits only scripts carrying it. */
function nonce(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}
