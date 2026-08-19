/** The Agents sidebar — an activity-bar panel you click, like Claude Code's own.
 *
 *  The dashboard is a WebviewPanel summoned by a command into an editor tab; close the tab and
 *  running agents are out of sight. Supervision has to live somewhere you can glance at while you
 *  work, so this is a real `TreeView` in its own view container.
 *
 *  Grouped by PROJECT (a run's `cwd`) by default, because that is how the work is actually
 *  divided — "what is running in this repo" is the question being asked. Provider and model
 *  groupings exist too, and the mode persists so the panel opens the way you left it.
 *
 *  Read-only over the registry Python writes (`interact.agents.registry`), refreshed by watching
 *  that directory. The extension never spawns or supervises anything itself.
 *
 *  The pure decisions below are exported and unit-tested in `agentsView.test.ts`; the tree class
 *  needs the `vscode` module, which only exists inside the extension host.
 */
import * as fs from "fs";
import * as vscode from "vscode";

import { AgentRun, readAgentActivity, readAgentRuns } from "./agents";
import { GroupBy, formatCost, groupKeyFor, orderGroups, rowDescription, statusIcon } from "./agentsFormat";
import { agentsDir } from "./paths";
import { orgTree, readOrg } from "./org";
import type { ScopeStore } from "./scopeStore";

export type { GroupBy };

const GROUP_KEY = "interact.agents.groupBy";


/** A group header, an agent, or one line of an agent's activity. */
export class Node extends vscode.TreeItem {
  constructor(
    label: string,
    collapsible: vscode.TreeItemCollapsibleState,
    public readonly kind: "group" | "run" | "event",
    public readonly run?: AgentRun,
  ) {
    super(label, collapsible);
  }
}

export class AgentsProvider implements vscode.TreeDataProvider<Node>, vscode.Disposable {
  private readonly emitter = new vscode.EventEmitter<Node | undefined>();
  readonly onDidChangeTreeData = this.emitter.event;
  private watcher: fs.FSWatcher | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  /** Ticks while anything runs, so elapsed times advance even with no registry write. */
  private ticker: ReturnType<typeof setInterval> | undefined;

  /** Which workspace to show. Set once at activation; the panels share ONE store so the tree and
   *  the workplace can never disagree about which team you are looking at. */
  scopeStore: ScopeStore | undefined;

  constructor(private readonly memento: vscode.Memento) {
    this.watch();
  }

  get groupBy(): GroupBy {
    return this.memento.get<GroupBy>(GROUP_KEY, "project");
  }

  async setGroupBy(by: GroupBy): Promise<void> {
    await this.memento.update(GROUP_KEY, by);
    this.refresh();
  }

  refresh(): void {
    this.emitter.fire(undefined);
  }

  /** Watch the registry directory. It is created lazily by the first spawn, so it is made here —
   *  otherwise the watch would silently attach to nothing and the panel would never update. */
  private watch(): void {
    try {
      const dir = agentsDir();
      fs.mkdirSync(dir, { recursive: true });
      this.watcher = fs.watch(dir, () => {
        if (this.timer) clearTimeout(this.timer);
        this.timer = setTimeout(() => this.refresh(), 250); // debounce a burst of writes
      });
      this.watcher.on("error", () => {});
    } catch {
      /* unwatchable → the ticker below still refreshes while work is live */
    }
    this.ticker = setInterval(() => {
      if (readAgentRuns().some((r) => r.status === "running")) this.refresh();
    }, 2000);
  }

  dispose(): void {
    this.watcher?.close();
    if (this.timer) clearTimeout(this.timer);
    if (this.ticker) clearInterval(this.ticker);
  }

  getTreeItem(node: Node): vscode.TreeItem {
    return node;
  }

  getChildren(node?: Node): Node[] {
    if (!node) return this.roots();
    if (node.kind === "group") return this.runsFor(String(node.label));
    // A run's children are the agents it SENT OUT first, then its own activity: a sub-agent
    // belongs inside its parent's context, not loose beside it as a sibling of its own boss.
    if (node.kind === "run" && node.run) {
      return [...this.reportsFor(node.run), ...this.activityFor(node.run)];
    }
    if (node.contextValue === "interactCompany" || node.contextValue === "interactDepartment") {
      return this.companyChildren(String(node.label));
    }
    return [];
  }

  /** The company as the prompt repo declares it: departments, and who sits in each.
   *
   *  Read from `~/.claude/org.json`, which the prompt repo generates from its own yaml. Absent for
   *  anyone without that repo, in which case there is simply no company node — interact is
   *  perfectly usable as a bare agent runner.
   */
  private companyNode(): Node | undefined {
    const org = readOrg();
    if (!org || org.agents.length === 0) return undefined;
    const node = new Node("Company", vscode.TreeItemCollapsibleState.Collapsed, "group");
    const wired = new Set(
      org.agents.flatMap((a) => a.providers ?? []).filter((p) => org.providers[p]?.env),
    );
    node.description = `${org.agents.length} agents · ${orgTree(org).length} departments` +
      (wired.size ? ` · ${[...wired].join(", ")}` : "");
    node.iconPath = new vscode.ThemeIcon("organization");
    node.contextValue = "interactCompany";
    return node;
  }

  /** A department, or the people in one. */
  private companyChildren(label: string): Node[] {
    const org = readOrg();
    if (!org) return [];
    const tree = orgTree(org);
    if (label === "Company") {
      return tree.map((dept) => {
        const n = new Node(dept.id, vscode.TreeItemCollapsibleState.Collapsed, "group");
        n.description = `${dept.agents.length} · ${dept.mission ?? ""}`.trim();
        n.iconPath = new vscode.ThemeIcon("folder-library");
        n.contextValue = "interactDepartment";
        return n;
      });
    }
    const dept = tree.find((d) => d.id === label);
    return (dept?.agents ?? []).map((seat) => {
      const n = new Node(seat.name, vscode.TreeItemCollapsibleState.None, "event");
      // Where it can actually RUN, not merely where it is designed to: an agent shared across
      // providers but wired into none of them is part of the company with nowhere to work.
      const live = seat.providers.filter((p) => p.env).map((p) => p.id);
      const designed = seat.providers.filter((p) => !p.env).map((p) => p.id);
      n.description = [seat.title, live.length ? live.join("+") : "not wired anywhere",
                       designed.length ? `(${designed.join(",")} designed)` : ""]
        .filter(Boolean).join(" · ");
      n.tooltip = seat.description ?? seat.title ?? seat.name;
      n.iconPath = new vscode.ThemeIcon(live.length ? "person" : "person-add");
      n.contextValue = "interactSeat";
      return n;
    });
  }

  private roots(): Node[] {
    const runs = this.scopeStore ? this.scopeStore.runs() : readAgentRuns();
    // The COMPANY comes first, and is there whether or not anybody is running: a roster you can
    // only see while its members happen to be working is not a roster. It is where "we have way
    // more agents than are in the env" becomes visible — each one shows where it can actually run.
    const company = this.companyNode();
    if (runs.length === 0) {
      const empty = new Node("No agents running", vscode.TreeItemCollapsibleState.None, "event");
      empty.description = 'interact agents run "<task>"';
      empty.iconPath = new vscode.ThemeIcon("info");
      return company ? [company, empty] : [empty];
    }
    const head = company ? [company] : [];
    if (this.groupBy === "flat") return [...head, ...runs.map((r) => this.runNode(r))];

    const groups = new Map<string, AgentRun[]>();
    for (const run of runs) {
      const key = groupKeyFor(run, this.groupBy);
      const bucket = groups.get(key);
      if (bucket) bucket.push(run);
      else groups.set(key, [run]);
    }
    return [...head, ...orderGroups([...groups.entries()]).map(([label, rs]) => {
      const node = new Node(label, vscode.TreeItemCollapsibleState.Expanded, "group");
      const live = rs.filter((r) => r.status === "running").length;
      const cost = rs.reduce((sum, r) => sum + (r.cost_usd ?? 0), 0);
      const known = rs.some((r) => r.cost_usd != null);
      node.description =
        `${live ? `${live} running · ` : ""}${rs.length} agent${rs.length > 1 ? "s" : ""}` +
        ` · ${known ? formatCost(cost) : "—"}`;
      node.iconPath = new vscode.ThemeIcon(live ? "folder-active" : "folder");
      node.contextValue = "interactGroup";
      return node;
    })];
  }

  private runsFor(label: string): Node[] {
    const all = readAgentRuns();
    const ids = new Set(all.map((r) => r.run_id));
    return all
      .filter((r) => groupKeyFor(r, this.groupBy) === label)
      // Only the leads at this level — a sub-agent is shown under whoever sent it. A run whose
      // parent is not in the list (its parent has been forgotten) is a lead again, never lost.
      .filter((r) => !r.parent_run_id || !ids.has(r.parent_run_id))
      .map((r) => this.runNode(r));
  }

  /** The agents this run sent out. */
  private reportsFor(run: AgentRun): Node[] {
    return readAgentRuns()
      .filter((r) => r.parent_run_id === run.run_id)
      .map((r) => this.runNode(r));
  }

  private runNode(run: AgentRun): Node {
    const hasReports = readAgentRuns().some((r) => r.parent_run_id === run.run_id);
    const hasActivity = hasReports || readAgentActivity(run.run_id, 1).length > 0;
    const node = new Node(
      run.name || run.run_id.slice(0, 8),
      hasActivity ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None,
      "run",
      run,
    );
    // Clicking a run aims the Chat view below at it — the reason to have a tree at all is to get
    // there. That view shows the same transcript AND lets you reply, so it strictly beats opening
    // a read-only editor tab; the tab is still one click away on the row's own icon.
    node.command = {
      command: "interact.agents.chat",
      title: "Open agent chat",
      arguments: [run.run_id],
    };
    const icon = statusIcon(run.status);
    node.iconPath = new vscode.ThemeIcon(
      icon.id,
      icon.color ? new vscode.ThemeColor(icon.color) : undefined,
    );
    // What it is doing RIGHT NOW is the most valuable string here, so it takes the description
    // slot; time and cost follow it.
    // The last thing that happened gets the row's whole width; elapsed and cost live on the hover
    // and on the dashboard, and competing for a narrow side bar clipped the interesting half.
    node.description = rowDescription(run);
    node.tooltip = new vscode.MarkdownString(
      [
        `**${run.name}** — ${run.status}`,
        run.task ? `\n${run.task}\n` : "",
        `- provider: \`${run.provider}\`${run.model ? ` · model: \`${run.model}\`` : ""}`,
        `- project: \`${run.cwd || "—"}\``,
        `- cost: ${formatCost(run.cost_usd)} — API-equivalent; a subscription run already paid for it`,
        `- id: \`${run.run_id}\``,
        run.foreign ? "\n_Not started by interact — one of your own sessions._" : "",
      ].join("\n"),
    );
    // Only OUR runs can be stopped; a foreign session belongs to the user's own editor window.
    node.contextValue = run.foreign
      ? "interactForeignRun"
      : run.status === "running"
        ? "interactRunningRun"
        : "interactRun";
    return node;
  }

  private activityFor(run: AgentRun): Node[] {
    return readAgentActivity(run.run_id, 25)
      .slice()
      .reverse() // newest first — the useful end of a long transcript
      .map((a) => {
        const node = new Node(
          (a.tool || a.text || a.kind).slice(0, 120),
          vscode.TreeItemCollapsibleState.None,
          "event",
        );
        node.iconPath = new vscode.ThemeIcon(
          a.kind === "tool" ? "tools" : a.kind === "error" ? "error" : "circle-small-filled",
        );
        node.description = a.kind;
        return node;
      });
  }
}
