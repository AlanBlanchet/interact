/** The one place that knows which workspace the panels are showing.
 *
 *  Deliberately shared rather than duplicated: the tree, the workplace and the sequence view each
 *  read runs independently today, and two copies of a rule drifting is precisely how the pod
 *  colours ended up disagreeing between the two panels. One store, one answer.
 */
import * as vscode from "vscode";

import { readAgentRuns, type AgentRun } from "./agents";
import { projectFor, scopeRuns, describeScope, scopeChoices, type Scope } from "./workspaceScope";

const SCOPE_KEY = "interact.agents.scope";

export class ScopeStore {
  private readonly changed = new vscode.EventEmitter<void>();
  /** Fires when the scope changes, so every view re-reads rather than showing a stale workspace. */
  readonly onDidChange = this.changed.event;

  constructor(private readonly memento: vscode.Memento) {}

  get scope(): Scope {
    return this.memento.get<Scope>(SCOPE_KEY, { kind: "current" });
  }

  /** The project the open folder belongs to, by the same rule the registry stamps onto a run. */
  get currentProject(): string {
    const folder = vscode.workspace.workspaceFolders?.[0];
    return folder ? projectFor(folder.uri.fsPath) : "";
  }

  /** Every run the panel should be showing. */
  runs(): AgentRun[] {
    return scopeRuns(readAgentRuns(), this.scope, this.currentProject);
  }

  /** What the panel is showing, for a title or a status line. */
  describe(): string {
    return describeScope(this.scope, this.currentProject);
  }

  /** Offer the switcher and apply the answer. Returns whether the scope moved. */
  async pick(): Promise<boolean> {
    const choices = scopeChoices(readAgentRuns(), this.currentProject);
    const chosen = await vscode.window.showQuickPick(
      choices.map((c) => ({ label: c.label, detail: c.detail, scope: c.scope })),
      { title: "Show agents from", placeHolder: this.describe() },
    );
    if (!chosen) return false;
    await this.memento.update(SCOPE_KEY, chosen.scope);
    this.changed.fire();
    return true;
  }
}


/** The one live store.
 *
 *  Held here rather than passed into each view because the workplace panel is imported lazily —
 *  it cannot be handed anything at activation time. A single accessor also makes it impossible
 *  for two views to end up holding different stores, which is the failure this whole module
 *  exists to prevent.
 */
let current: ScopeStore | undefined;

export function setScopeStore(store: ScopeStore): void {
  current = store;
}

export function scopeStore(): ScopeStore | undefined {
  return current;
}
