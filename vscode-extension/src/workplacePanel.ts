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
import { selectedRunId } from "./workplaceMessage";
import { renderScene, renderWorkplace } from "./workplaceView";
import type { TeamState } from "./team";
import { scopeStore } from "./scopeStore";
import { claimColumn, nextColumn, releaseColumn } from "./panelColumn";

export class WorkplacePanel {
  private static current: WorkplacePanel | undefined;
  private watcher: fs.FSWatcher | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private readonly log: vscode.OutputChannel,
  ) {
    this.panel.onDidDispose(() => this.dispose());
    // One column for interact's surfaces: a new one joins the group its siblings already
    // hold rather than opening yet another beside your code.
    claimColumn("workplace", this.panel.viewColumn);
    // A click in the room aims the side-bar Chat at that agent: the workplace is where you SEE
    // the team, the chat is where you talk to one of them, and this is the seam between.
    this.panel.webview.onDidReceiveMessage((msg) => {
      // Two shapes on purpose: `select`/`run_id` is what the pixel-art scene posts, `focus`/`runId`
      // what the plain fallback does. Accepting only one was why clicking a sprite did nothing at
      // all — the hook was there, the two halves just never agreed on the word.
      const runId = selectedRunId(msg);
      if (runId) void vscode.commands.executeCommand("interact.agents.chat", runId);
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
      nextColumn() as vscode.ViewColumn,
      { enableScripts: true, retainContextWhenHidden: true },
    );
    WorkplacePanel.current = new WorkplacePanel(panel, log);
  }

  /** Everyone in the building right now, placed by what they are doing. */
  private state(): TeamState {
    return buildTeam(
      (scopeStore()?.runs() ?? readAgentRuns()) as never,
      // The whole recent window, not one event: the vendor emits housekeeping constantly, and a
      // finished worker's room is found by walking back to the last thing it actually did.
      (runId) => readAgentActivity(runId, STEP_WINDOW),
      Date.now() / 1000,
      readAgentMessages() as never,
    );
  }

  /** Re-draw if the building is on screen — the workspace switcher has to reach it too, or the
   *  tree changes workspace and the building carries on showing the old team. */
  public static refreshIfOpen(): void {
    WorkplacePanel.current?.render();
  }

  /** Whether the document exists yet. Assigning `webview.html` REBUILDS it — every sprite becomes
   *  a new element, every running animation dies, and there is no clock — so it happens once. */
  private mounted = false;

  private render(): void {
    const state = this.state();
    // Once the document is up, push the new scene into it instead of replacing it. This is the
    // difference between a slideshow and something you can watch: the engine keeps each body's
    // position and facing across the update, so a worker whose room changed WALKS there rather
    // than appearing in it.
    if (this.mounted) {
      const html = renderScene(state, this.log);
      if (html !== null) {
        void this.panel.webview.postMessage({ type: "team", html, state });
        return;
      }
      // No scene renderer (an old or broken bundle): fall back to rebuilding rather than freezing.
      this.mounted = false;
    }
    try {
      this.panel.webview.html = renderWorkplace(state, nonce(), this.log);
      this.mounted = true;
      // Straight after a rebuild, or the engine sits on the shell's snapshot until the next
      // registry write — which on a quiet team is minutes of a still picture.
      void this.panel.webview.postMessage({ type: "team", html: renderScene(state, this.log), state });
    } catch (err) {
      this.log.appendLine(`workplace render failed: ${err}`);
      this.panel.webview.html = `<!DOCTYPE html><body>${String(err)}</body>`;
      this.mounted = false;
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
    releaseColumn("workplace");
    clearTimeout(this.timer);
    this.watcher?.close();
    this.watcher = undefined;
    WorkplacePanel.current = undefined;
  }
}

//: How far back to look for the step that says what someone is doing. Enough to see past a run
//: of housekeeping lines, small enough that a busy registry stays cheap to read per refresh.
const STEP_WINDOW = 12;

/** A fresh nonce per render: the CSP admits only scripts carrying it. */
function nonce(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}
