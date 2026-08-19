/** The rail, wired into the sidebar as a real view.
 *
 *  This is the panel Alan chose from three measured alternatives ("one panel, one rail"), and the
 *  reason it is a webview rather than a `TreeView` was measured on a real editor: VS Code shows a
 *  view's title actions only while the pointer is inside the header and CLIPS the overflow with no
 *  menu, so a resting panel rendered ZERO buttons and the team view could not be found at all. No
 *  arrangement of icons fixes that inside a tree, at any width.
 *
 *  The decisions and the rendering live in `rail.ts` / `railHtml.ts`, both pure and unit-tested.
 *  This file is the glue: the provider, the filesystem reads, and the routing of untrusted
 *  messages — which is itself split out as `railRoute` so it can be tested without a host.
 */
import * as vscode from "vscode";

import { readAgentActivity, readAgentRuns } from "./agents";
import { buildRail, railRoute } from "./rail";
import { railHtml } from "./railHtml";
import { lastObservedAt } from "./teamState";
import { scopeStore } from "./scopeStore";
import { describeScope, projectFor } from "./workspaceScope";

export class RailViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewId = "interactAgents.rail";

  private view: vscode.WebviewView | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly onOpen: (runId: string) => void) {}

  public resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true, enableCommandUris: true };
    view.webview.onDidReceiveMessage((msg) =>
      railRoute(msg, {
        run: (command) => void vscode.commands.executeCommand(command),
        open: (runId) => this.onOpen(runId),
      }),
    );
    view.onDidChangeVisibility(() => { if (view.visible) this.render(); });
    this.render();
  }

  /** Re-draw, coalesced: the registry is written in bursts while a team works, and repainting per
   *  write makes the panel stutter while agents are running. */
  public refresh(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.render(), 200);
  }

  /** The project of the folder you have open — what "current" means in the scope label. */
  private static currentProject(): string {
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    return folder ? projectFor(folder) : "";
  }

  private render(): void {
    if (!this.view?.visible) return;
    const store = scopeStore();
    const runs = store?.runs() ?? readAgentRuns();
    const now = Date.now() / 1000;
    const rail = buildRail(
      runs,
      store ? describeScope(store.scope, RailViewProvider.currentProject()) : "",
      // Idleness is time since the run was last OBSERVED doing something — not since it started,
      // which would mark every long-running agent as stalled the moment it got going.
      (run) => Math.max(0, now - (lastObservedAt(readAgentActivity(run.run_id, 40)) ?? now)),
    );
    this.view.webview.html = railHtml(
      rail,
      // A fresh nonce per render: the CSP admits only scripts carrying it, so nothing arriving in
      // an agent's output can execute even if the escaping were ever wrong.
      Math.random().toString(36).slice(2) + Date.now().toString(36),
    );
  }
}
