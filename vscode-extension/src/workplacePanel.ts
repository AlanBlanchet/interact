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
import { facultiesOf, parseCapabilities } from "./capabilities";
import { companyOf, readOrg } from "./org";
import { claimColumn, nextColumn, releaseColumn } from "./panelColumn";
import { buildRail, railRoute } from "./rail";
import { railBody, railScript, railStyle } from "./railHtml";
import { actionsFor } from "./agentActions";
import { agentLabel, conversationTitle, roleOf } from "./roster";
import { voiceOf } from "./statusLanguage";
import { lastObservedAt } from "./teamState";
import { describeScope, projectFor } from "./workspaceScope";

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
      if (runId) {
        // A character IS an agent now, so clicking one opens that agent and the errands it was
        // given, rather than dropping you into whichever single run happened to speak for it.
        const run = readAgentRuns().find((r) => r.run_id === runId);
        const company = companyOf(readOrg()) ?? undefined;
        const who = run ? roleOf(run as never, company) : null;
        if (who && !who.plain) void vscode.commands.executeCommand("interact.agents.agent", who.id);
        else void vscode.commands.executeCommand("interact.agents.chat", runId);
        return;
      }
      // The roster shares this document now, so its buttons arrive here too. Routed through the
      // same `railRoute` the side-bar view used, so what a row can do is decided in one place and
      // an untrusted message still cannot name an arbitrary command.
      railRoute(msg, {
        run: (command) => void vscode.commands.executeCommand(command),
        open: (id) => void vscode.commands.executeCommand("interact.agents.chat", id),
        agent: (id) => {
          this.inside = id;
          this.pushRoster();
          // "on the sidepanel, we should be able to view what TASKS an agent was given" — clicking
          // the role opens that depth beside the room rather than only narrowing the list here.
          if (id) void vscode.commands.executeCommand("interact.agents.agent", id);
        },
        act: (command, id) => {
          const run = readAgentRuns().find((r) => r.run_id === id);
          if (run) void vscode.commands.executeCommand(command, { run });
        },
      });
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

  /** What an agent can do, from its own definition file — cached, because the file changes only
   *  when the definition is edited and the building re-renders constantly. */
  private static readonly FACULTIES = new Map<string, string[]>();

  /** Everyone in the building right now, placed by what they are doing. */
  private state(): TeamState {
    return buildTeam(
      (scopeStore()?.runs() ?? readAgentRuns()) as never,
      // The whole recent window, not one event: the vendor emits housekeeping constantly, and a
      // finished worker's room is found by walking back to the last thing it actually did.
      (runId) => readAgentActivity(runId, STEP_WINDOW),
      Date.now() / 1000,
      readAgentMessages() as never,
      // What each one can DO, read from its own definition file. The parsing lives in
      // capabilities.ts and the filesystem read lives HERE, at the edge, so teamState stays pure.
      (run) => WorkplacePanel.facultiesOfDefinition(run.definition_path),
      // Which DOMAIN each one belongs to. The company file has declared these rooms all along —
      // Quality & Critics, Production & Makers, Research, Records, the Wealth Desk — and nothing
      // placed anybody by them, so a finance agent stood among the code reviewers.
      (agent) => WorkplacePanel.departmentOf(agent),
      // WHO each run was held with. One body per agent: five sessions recorded as `claude` are the
      // coordinator five times, not five teammates, and an agent given three errands is one
      // colleague — which is what "I can see multiple 'claude' agents... they're all duplicates"
      // was looking at.
      (run) => {
        const company = companyOf(readOrg()) ?? undefined;
        return {
          id: roleOf(run as never, company).id,
          label: agentLabel(run as never, company),
        };
      },
    );
  }

  /** The department a definition is filed under, from the company file. Cached with the
   *  faculties, for the same reason: the file changes when someone edits the org, not per frame. */
  private static departmentOf(agent: string): { id: string; room?: string | null } | null {
    const org = readOrg();
    if (!org) return null;
    const seat = org.agents.find((a) => a.name === agent);
    if (!seat?.department) return null;
    const dept = org.departments.find((d) => d.id === seat.department);
    return { id: seat.department, room: dept?.room ?? null };
  }

  /** Everything else is pure; the one filesystem read for capabilities lives here. */
  private static facultiesOfDefinition(path: string | null | undefined): string[] {
    if (!path) return [];
    const cached = WorkplacePanel.FACULTIES.get(path);
    if (cached) return cached;
    let found: string[] = [];
    try {
      found = facultiesOf(parseCapabilities(fs.readFileSync(path, "utf8")));
    } catch {
      found = []; // a moved or unreadable definition must not take the building down
    }
    WorkplacePanel.FACULTIES.set(path, found);
    return found;
  }

  /** Re-draw if the building is on screen — the workspace switcher has to reach it too, or the
   *  tree changes workspace and the building carries on showing the old team. */
  public static refreshIfOpen(): void {
    WorkplacePanel.current?.render();
  }

  /** Whether the document exists yet. Assigning `webview.html` REBUILDS it — every sprite becomes
   *  a new element, every running animation dies, and there is no clock — so it happens once. */
  private mounted = false;
  /** The agent whose conversations the roster is narrowed to, if you have gone into one. */
  private inside: string | null = null;

  /** The roster, as a fragment for the panel beside the room.
   *
   *  It used to be a side-bar view. "Your team and agents panel are still on the left side, whereas
   *  they should be in the big main panel somewhere" — the room and the roster are two views of one
   *  company, so they share a surface, and the side bar is left for the conversation.
   */
  private roster(): string {
    const company = companyOf(readOrg()) ?? undefined;
    const store = scopeStore();
    const runs = store?.runs() ?? readAgentRuns();
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const now = Date.now() / 1000;
    const rail = buildRail(
      runs,
      store ? describeScope(store.scope, folder ? projectFor(folder) : "") : "",
      // Idleness is time since the run was last OBSERVED doing something, not since it started.
      (run) => Math.max(0, now - (lastObservedAt(readAgentActivity(run.run_id, 40)) ?? now)),
      undefined,
      this.inside ? { agent: this.inside, roleOf: (r) => roleOf(r as never, company).id } : undefined,
    );
    return railBody(
      rail,
      voiceOf,
      (run) => conversationTitle(run as never),
      (run) => ({ id: roleOf(run as never, company).id, label: agentLabel(run as never, company) }),
      (run) => actionsFor(run as never),
    );
  }

  /** Repaint just the roster — going into an agent must not rebuild the room and restart every
   *  animation in it. */
  private pushRoster(): void {
    void this.panel.webview.postMessage({ type: "roster", html: this.roster() });
  }

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
        void this.panel.webview.postMessage({ type: "roster", html: this.roster() });
        return;
      }
      // No scene renderer (an old or broken bundle): fall back to rebuilding rather than freezing.
      this.mounted = false;
    }
    try {
      this.panel.webview.html = renderWorkplace(state, nonce(), this.log, {
        style: railStyle(), body: this.roster(), script: railScript(),
      });
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
