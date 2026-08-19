import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import {
  KeyManager,
  ModelsData,
  CellContent,
  CellUpdate,
  Action,
  RangeId,
  AgentLane,
  AgentGroupBy,
  cfg,
  SETTINGS,
  Setting,
  metaOf,
  ensureKeys,
} from "./shared";
import {
  usdRateTo,
  formatMoney,
  currencySymbol,
  COMMON_CURRENCIES,
} from "./currency";
import { scopeStore } from "./scopeStore";
import { readAgentRuns, summarise, withDepth } from "./agents";
import { describeAge as describeBoardAge, readLeaderboard } from "./leaderboard";
import { describeAge, ageSeconds, isLive, loadCatalog, pickHighlights, type Catalog } from "./catalog";
import { agentsDir, usageLogPathFor, INTERACT_CONFIG_PATH } from "./paths";
import { DIM_FOREGROUND } from "./themeTokens";
import {
  readUsageLog,
  filterByRange,
  aggregateByProvider,
  aggregateStackedByModel,
  aggregateTokensByModel,
  aggregateCallsByModel,
  colorFor,
} from "./usage";

function getNonce(): string {
  const chars =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let result = "";
  for (let i = 0; i < 32; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

const VIEW_TYPE = "interact.dashboard";

// Benchmark ids the dashboard surfaces. These are taxonomy ids (matches
// Benchmark.id in benchmarks.json), not domain data.
const RECOMMENDATION_BENCHMARK = "screenspot_pro";

interface PublishedEntryData {
  model_name: string;
  score: number;
}
interface PublishedTableData {
  source_url: string;
  retrieved: string;
  lib_recommendation: string | null;
  entries: PublishedEntryData[];
}
interface BenchmarkData {
  id: string;
  name: string;
  description: string;
  category: "image" | "gui_grounding" | "video";
  source: string;
  source_auth: string;
  url: string;
  metric: string;
  published: PublishedTableData | null;
  lib_recommendation_model_id: string | null;
  measured: Record<string, number>;
  recommendations: RecommendationData[];
}

// Display order + human labels for the three benchmark categories.
const BENCHMARK_CATEGORIES: { id: BenchmarkData["category"]; label: string }[] = [
  { id: "image", label: "Image understanding" },
  { id: "gui_grounding", label: "GUI grounding (where to click)" },
  { id: "video", label: "Video understanding" },
];
interface RecommendationData {
  model_id: string;
  score: number;
  source: "published" | "measured";
  rank: number;
  cost_per_million: number | null;
  quality_per_dollar: number | null;
}
export interface BenchmarksFile {
  benchmarks: BenchmarkData[];
}

function asBenchmarks(raw: unknown): BenchmarksFile {
  if (
    raw &&
    typeof raw === "object" &&
    Array.isArray((raw as { benchmarks?: unknown }).benchmarks)
  ) {
    return raw as BenchmarksFile;
  }
  return { benchmarks: [] };
}

export class DashboardPanel {
  static instance: DashboardPanel | undefined;
  private readonly panel: vscode.WebviewPanel;
  private disposed = false;
  private range: RangeId = "7d";
  /** How the agent board splits its lanes. Project first: the owner's own default question about a
   *  team is "what is happening on which of my repos". */
  private agentGroupBy: AgentGroupBy = "project";
  private watchers: fs.FSWatcher[] = [];
  private refreshTimer: ReturnType<typeof setTimeout> | undefined;

  private constructor(
    panel: vscode.WebviewPanel,
    private readonly extensionUri: vscode.Uri,
    private readonly keyManager: KeyManager,
    private readonly modelsData: ModelsData,
    private readonly benchmarksData: BenchmarksFile,
    private readonly emitter: vscode.EventEmitter<void>,
  ) {
    this.panel = panel;
    panel.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(extensionUri, "out")],
    };
    panel.webview.onDidReceiveMessage((msg) => this.handleMessage(msg));
    panel.onDidDispose(() => {
      this.disposed = true;
      this.stopWatching();
      DashboardPanel.instance = undefined;
    });
    panel.webview.html = this.getHtml();
    setTimeout(() => this.refresh(), 500);
    this.startWatching();
  }

  /** Path of the usage log the running server writes to — under the configured base dir, so a
   *  custom `interact.debug.dir` (== Python's INTERACT_DEBUG_DIR) is honoured, not hardcoded. */
  private usageLogPath(): string {
    return usageLogPathFor(cfg().get<string>("debug.dir") || "");
  }

  /** Live-sync the panel: the MCP server is a SEPARATE process that appends to the usage log and
   *  config.env as you work, so without watching them the panel would freeze at open time. Watch
   *  the usage log's dir and config.env's dir, debounced into one refresh. config.env is located
   *  DIRECTLY (not as the log dir's parent): the two move independently — point `interact.debug.dir`
   *  at a project's out/ and the parent is that project, not `~/.interact`, so walking up would
   *  both miss key/setting edits and watch an unrelated directory. */
  private startWatching(): void {
    const dirs = new Set([
      path.dirname(this.usageLogPath()),
      path.dirname(INTERACT_CONFIG_PATH),
      // Agent runs appear and change here; without this a spawned agent would sit invisible
      // until something else happened to trigger a refresh.
      agentsDir(),
    ]);
    for (const dir of dirs) {
      try {
        fs.mkdirSync(dir, { recursive: true });
        const w = fs.watch(dir, () => this.scheduleRefresh());
        w.on("error", () => {}); // a transient watch error must not crash the panel
        this.watchers.push(w);
      } catch {
        /* unwatchable dir → just no live updates from it */
      }
    }
  }

  private stopWatching(): void {
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
    for (const w of this.watchers) {
      try {
        w.close();
      } catch {
        /* already closed */
      }
    }
    this.watchers = [];
  }

  private scheduleRefresh(): void {
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
    this.refreshTimer = setTimeout(() => this.refresh(), 300); // coalesce bursty appends
  }

  static createOrShow(
    extensionUri: vscode.Uri,
    keyManager: KeyManager,
    modelsData: ModelsData,
    benchmarksRaw: unknown,
    emitter: vscode.EventEmitter<void>,
  ): DashboardPanel {
    if (DashboardPanel.instance) {
      DashboardPanel.instance.panel.reveal(vscode.ViewColumn.Beside);
      return DashboardPanel.instance;
    }
    const panel = vscode.window.createWebviewPanel(
      VIEW_TYPE,
      "Interact",
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        localResourceRoots: [vscode.Uri.joinPath(extensionUri, "out")],
      },
    );
    DashboardPanel.instance = new DashboardPanel(
      panel,
      extensionUri,
      keyManager,
      modelsData,
      asBenchmarks(benchmarksRaw),
      emitter,
    );
    return DashboardPanel.instance;
  }

  static registerSerializer(
    extensionUri: vscode.Uri,
    keyManager: KeyManager,
    modelsData: ModelsData,
    benchmarksRaw: unknown,
    emitter: vscode.EventEmitter<void>,
  ): vscode.Disposable {
    return vscode.window.registerWebviewPanelSerializer(VIEW_TYPE, {
      async deserializeWebviewPanel(panel: vscode.WebviewPanel) {
        DashboardPanel.instance = new DashboardPanel(
          panel,
          extensionUri,
          keyManager,
          modelsData,
          asBenchmarks(benchmarksRaw),
          emitter,
        );
      },
    });
  }

  static refreshIfOpen(): void {
    DashboardPanel.instance?.refresh();
  }

  async refresh(): Promise<void> {
    if (this.disposed) return;
    const cells: CellUpdate[] = [
      this.statusCell(),
      this.apiKeysCell(),
      ...this.settingsCells(),
      this.benchmarkDataCell(),
      this.displayCell(),
      this.agentsCell(),
      await this.modelsCell(),
      await this.consumptionCell(),
      this.benchmarksCell(),
      this.recommendationsCell(),
    ];
    for (const cell of cells) {
      this.panel.webview.postMessage({ type: "cellUpdate", cell });
    }
  }

  private async handleMessage(msg: {
    type: string;
    setting?: string;
    provider?: string;
    key?: string;
  }): Promise<void> {
    switch (msg.type) {
      case "ready":
        this.refresh();
        break;
      case "configureProvider": {
        if (!msg.provider) return;
        await ensureKeys(msg.provider, this.modelsData, this.keyManager, this.emitter);
        this.refresh();
        break;
      }
      case "removeProvider": {
        if (!msg.provider) return;
        const info = this.modelsData.providers[msg.provider];
        if (!info) return;
        for (const k of info.envKeys) {
          await this.keyManager.remove(k);
        }
        this.emitter.fire();
        this.refresh();
        break;
      }
      case "changeModel": {
        await vscode.commands.executeCommand("interact.selectModel");
        this.refresh();
        break;
      }
      case "changeSetting": {
        const setting = SETTINGS.find((s) => s.key === msg.setting);
        if (setting) await this.editSetting(setting);
        break;
      }
      case "setBenchmarkKey": {
        if (!msg.key) break;
        const value = await vscode.window.showInputBox({
          prompt: `${msg.key} — key for a benchmark data source (improves model recommendations)`,
          password: true,
          ignoreFocusOut: true,
        });
        if (value) {
          await this.keyManager.set(msg.key, value);
          this.emitter.fire(); // re-inject into the server env
          this.refresh();
        }
        break;
      }
      case "clearBenchmarkKey": {
        if (!msg.key) break;
        await this.keyManager.remove(msg.key);
        this.emitter.fire();
        this.refresh();
        break;
      }
      case "changeCurrency": {
        const pick = await vscode.window.showQuickPick(COMMON_CURRENCIES, {
          placeHolder: "Display currency for spend (live ECB conversion)",
        });
        if (pick) {
          await cfg().update("display.currency", pick, vscode.ConfigurationTarget.Global);
          this.refresh();
        }
        break;
      }
      case "refresh":
        this.refresh();
        break;
      case "reloadPanel":
        this.reload();
        break;
      case "setRange": {
        const next = (msg as { range?: string }).range;
        if (next === "24h" || next === "7d" || next === "30d" || next === "all") {
          this.range = next;
          this.refresh();
        }
        break;
      }
      case "setAgentGroup": {
        // The webview already re-rendered optimistically; this only makes the choice survive the
        // next refresh, so no round-trip is on the interaction's critical path.
        const next = (msg as { group?: string }).group;
        if (next === "project" || next === "provider" || next === "model" || next === "none") {
          this.agentGroupBy = next;
        }
        break;
      }
    }
  }

  /** Prompt for a setting's new value with the control its kind implies (enum/bool → quick-pick,
   *  numbers/strings/paths → input box), then persist it. Empty clears the override (→ default). */
  private async editSetting(s: Setting): Promise<void> {
    const current = cfg().get<string | number | boolean>(s.key);
    let value: string | number | boolean | undefined;
    if (s.kind === "bool") {
      const pick = await vscode.window.showQuickPick(["on", "off"], {
        placeHolder: `${s.label} — ${s.description}`,
      });
      if (pick === undefined) return;
      value = pick === "on";
    } else if (s.kind === "enum") {
      const pick = await vscode.window.showQuickPick(
        (s.options ?? []).map((o) => ({ label: o.label, value: o.value })),
        { placeHolder: `${s.label} — ${s.description}` },
      );
      if (!pick) return;
      value = pick.value;
    } else {
      const text = await vscode.window.showInputBox({
        prompt: `${s.label} — ${s.description}`,
        value: current === undefined ? "" : String(current),
        placeHolder: s.default ? `default: ${s.default}` : "",
        ignoreFocusOut: true,
      });
      if (text === undefined) return;
      value =
        text === "" ? undefined : s.kind === "int" ? Number(text) : text;
    }
    await cfg().update(s.key, value, vscode.ConfigurationTarget.Global);
    this.refresh();
  }

  private statusCell(): CellUpdate {
    const projectPath = cfg().get<string>("projectPath") || "(auto-detect)";
    return {
      id: "status",
      title: "System Status",
      content: [
        { kind: "row", label: "Extension Active", dot: "ok" },
        { kind: "row", label: "Project:", value: projectPath },
      ],
    };
  }

  private apiKeysCell(): CellUpdate {
    const providers = Object.entries(this.modelsData.providers).filter(
      ([, info]) => info.envKeys.length > 0,
    );
    if (!providers.length) {
      return {
        id: "apiKeys",
        title: "API Keys",
        content: [{ kind: "empty", message: "No model data available" }],
      };
    }
    const content: CellContent[] = providers.map(([name, info]) => {
      const allConfigured = info.envKeys.every((k) => this.keyManager.get(k));
      const actions: Action[] = allConfigured
        ? [{ type: "removeProvider", label: "Remove Keys", data: { provider: name }, style: "secondary" as const }]
        : [{ type: "configureProvider", label: "Configure", data: { provider: name } }];
      return {
        kind: "row" as const,
        label: name,
        dot: allConfigured ? ("ok" as const) : ("missing" as const),
        actions,
      };
    });
    return { id: "apiKeys", title: "API Keys", content };
  }

  /** One row for a setting: current value (or its auto/default) + a Change action; model rows
   *  also show cost and the fallback chain. */
  private settingRows(s: Setting): CellContent[] {
    const recs = this.modelsData.recommendations || {};
    const raw = cfg().get<string | number | boolean>(s.key);
    const isSet = raw !== undefined && raw !== "";
    let value = isSet ? String(raw) : `auto · ${s.default || "default"}`;
    const action = s.kind === "model" ? "changeModel" : "changeSetting";
    if (s.kind === "model" && isSet) {
      const meta = metaOf(String(raw), this.modelsData);
      if (meta?.input_cost_per_million) {
        value += ` — $${meta.input_cost_per_million}/M in, $${meta.output_cost_per_million ?? 0}/M out`;
      }
    }
    const rows: CellContent[] = [
      {
        kind: "row",
        label: s.label,
        value,
        tooltip: s.description,
        actions: [{ type: action, label: "Change", data: { setting: s.key } }],
      },
    ];
    if (s.kind === "model") {
      const chain = (recs[s.role ?? ""] || []).filter((m) => m !== raw).slice(0, 3);
      if (chain.length) {
        rows.push({
          kind: "row",
          label: "  ↳ fallback chain",
          value: chain.join(" → "),
          tooltip: "If the primary model fails, the next is tried automatically (max 3).",
        });
      }
    }
    return rows;
  }

  /** One sub-panel (card) per schema group — Models / Desktop / Browser / Advanced — so the
   *  Configuration tab reads as distinct sections rather than one long list. Cell id is
   *  `cfg-<group>` (the webview lists these); all driven by the shared settings schema. */
  private settingsCells(): CellUpdate[] {
    const byGroup = new Map<string, CellContent[]>();
    for (const s of SETTINGS) {
      const rows = byGroup.get(s.group) ?? [];
      rows.push(...this.settingRows(s));
      byGroup.set(s.group, rows);
    }
    return [...byGroup].map(([group, content]) => ({
      id: `cfg-${group.toLowerCase()}`,
      title: group,
      content,
    }));
  }

  /** Benchmark data sources — where each benchmark's live scores come from and the optional key
   *  that source needs. Lets the user supply keys in-UI (no CLI), grouped per benchmark, with a
   *  nudge: live scores let interact recommend the best current model. */
  private benchmarkDataCell(): CellUpdate {
    const content: CellContent[] = [
      {
        kind: "row",
        label:
          "interact ranks models from public benchmark scores. Add a source key below to fetch " +
          "live data so it knows the best current model — optional; curated snapshots are used otherwise.",
      },
    ];
    for (const cat of BENCHMARK_CATEGORIES) {
      const benches = this.benchmarksData.benchmarks.filter((b) => b.category === cat.id);
      if (!benches.length) continue;
      content.push({ kind: "heading", text: cat.label });
      for (const b of benches) {
        if (b.source_auth) {
          const set = !!this.keyManager.get(b.source_auth);
          content.push({
            kind: "row",
            label: b.name,
            value: `${b.source} · ${set ? "key set" : "needs a key"}`,
            dot: set ? "ok" : "missing",
            tooltip: `${b.source_auth} — ${b.description}`,
            actions: set
              ? [
                  { type: "clearBenchmarkKey", label: "Clear", data: { key: b.source_auth }, style: "secondary" },
                ]
              : [{ type: "setBenchmarkKey", label: "Add key", data: { key: b.source_auth } }],
          });
        } else {
          content.push({
            kind: "row",
            label: b.name,
            value: `${b.source} · auto · no key needed`,
            dot: "ok",
            tooltip: b.description,
          });
        }
      }
    }
    return { id: "cfg-benchmarks", title: "Benchmark data", content };
  }

  /** Display preferences (UI-only, not server config) — currently the spend display currency. */
  private displayCell(): CellUpdate {
    const cur = cfg().get<string>("display.currency") || "USD";
    return {
      id: "cfg-display",
      title: "Display",
      content: [
        {
          kind: "row",
          label: "Currency",
          value: cur,
          tooltip:
            "Spend is recorded in USD and converted at live ECB rates (frankfurter.app) for display only.",
          actions: [{ type: "changeCurrency", label: "Change" }],
        },
      ],
    };
  }

  /** The agent team: what is running, what each is doing, and what it has cost.
   *
   *  Costs are labelled API-EQUIVALENT because a subscription run is already paid for by the
   *  plan — showing a bare currency figure would read as fresh spend. A run with no reported
   *  cost shows "—", never "$0.00", because unknown is not free.
   *
   *  Runs interact did NOT spawn (the user's own editor windows) are marked, so the panel is an
   *  honest view of the machine rather than only of our own children.
   */
  private agentsCell(): CellUpdate {
    // Under the workspace scope, like every other surface. "Showing every run on the machine,
    // unscoped, is not an acceptable default" is a recorded decision, and this panel was quietly
    // exempt from it — you switched workspace in the tree and the dashboard kept describing the
    // folder you left.
    const runs = scopeStore()?.runs() ?? readAgentRuns();
    if (runs.length === 0) {
      return {
        id: "agents",
        title: "Agent supervision",
        content: [
          {
            kind: "empty",
            message:
              "No agent runs yet. Once a team is working, every run appears here as a lane on a " +
              "shared clock \u2014 who is running, on what, for how long, and who launched whom.",
            hint: 'interact agents run "<task>"',
          },
        ],
      };
    }

    const now = Date.now();
    const lanes: AgentLane[] = withDepth(runs).map(({ run, depth }) => {
      // Python stamps epoch SECONDS; the board works in milliseconds. A record with no start (an
      // older writer) is pinned to `now` so it still draws instead of flying off the axis.
      const cwd = run.cwd || undefined;
      return {
        id: run.run_id,
        name: run.name,
        provider: run.provider,
        model: run.model || undefined,
        project: cwd ? cwd.split(/[\\/]/).filter(Boolean).pop() : undefined,
        cwd,
        task: run.task || undefined,
        // `foreign` is provenance rather than lifecycle, but it is the read that matters here: a
        // session interact did not spawn is drawn as a ghost, never as our own work.
        status: run.foreign ? "foreign" : run.status,
        parentId: run.parent_run_id ?? null,
        depth,
        startedAt: run.started_at ? run.started_at * 1000 : now,
        // An absent `finished_at` stays null all the way to the renderer, which draws an explicit
        // unknown end. Substituting `now` here would invent a duration nothing ever recorded.
        endedAt: run.finished_at != null ? run.finished_at * 1000 : null,
        costUsd: run.cost_usd ?? null,
        last: run.last || undefined,
      };
    });

    const { live, cost } = summarise(runs);
    // At least a minute of window, so a team that all started seconds ago still gets an axis.
    const windowStart = Math.min(...lanes.map((l) => l.startedAt), now - 60_000);
    return {
      id: "agents",
      title: "Agent supervision",
      content: [
        {
          kind: "agent-board",
          groupBy: this.agentGroupBy,
          lanes,
          windowStart,
          now,
          ariaSummary:
            `${live} of ${lanes.length} agents running; ~$${cost.toFixed(4)} API-equivalent ` +
            "value consumed, already covered by the plan.",
        },
      ],
    };
  }

  /** Live model metadata, with its age on the label.
   *
   *  The panel used to render `models.json` — baked into the bundle at BUILD time, so prices and
   *  context windows silently aged and nothing said so. This shows the live catalog and, when it
   *  is NOT live (offline, or an old cache), says how old it is rather than presenting a snapshot
   *  as today's truth. No API key: OpenRouter's catalog endpoint is public.
   */
  private async modelsCell(): Promise<CellUpdate> {
    let cat: Catalog | null = null;
    try {
      cat = await loadCatalog();
    } catch {
      cat = null;
    }
    if (!cat || cat.models.length === 0) {
      return {
        id: "models",
        title: "Models",
        content: [
          {
            kind: "empty",
            message:
              "No live catalog yet — needs one network call to openrouter.ai (no API key). " +
              "It will populate on the next refresh when you are online.",
          },
        ],
      };
    }
    const fresh = isLive(cat);
    const age = describeAge(ageSeconds(cat));
    const rows = pickHighlights(cat, 8).map((m) => [
      m.name,
      m.context_length ? `${Math.round(m.context_length / 1000)}k` : "—",
      m.input_cost_per_token ? `$${(m.input_cost_per_token * 1e6).toFixed(2)}/M` : "—",
      (m.input_modalities || []).filter((x) => x !== "text").join(", ") || "text",
    ]);
    return {
      id: "models",
      title: `Models \u2014 ${cat.models.length} \u00b7 ${fresh ? `live, ${age}` : `${cat.source}, ${age}`}`,
      content: [
        ...(fresh
          ? []
          : ([
              {
                kind: "row",
                label: "Not live",
                value: `showing ${cat.source} data from ${age}`,
                dot: "missing",
              },
            ] as CellContent[])),
        { kind: "table", headers: ["Model", "Context", "Input", "Sees"], rows },
      ],
    };
  }

  private async consumptionCell(): Promise<CellUpdate> {
    const all = await readUsageLog(this.usageLogPath());
    const entries = filterByRange(all, this.range);

    const rangeSelector: CellContent = {
      kind: "range-selector",
      current: this.range,
      options: [
        { id: "24h", label: "Last 24h" },
        { id: "7d", label: "7d" },
        { id: "30d", label: "30d" },
        { id: "all", label: "All" },
      ],
    };

    if (!entries.length) {
      return {
        id: "consumption",
        title: "Consumption",
        content: [
          rangeSelector,
          {
            kind: "empty",
            message:
              "Run a few MCP tool calls to populate consumption charts.",
          },
        ],
      };
    }

    const rangeLabel =
      this.range === "all" ? "all time" : `last ${this.range}`;
    const stackedDays =
      this.range === "24h" ? 1 : this.range === "30d" ? 30 : this.range === "all" ? 30 : 14;

    // Spend is recorded in USD; convert to the user's display currency at a live ECB rate.
    const currency = cfg().get<string>("display.currency") || "USD";
    const rate = await usdRateTo(currency);
    const sym = currencySymbol(currency);
    const money = (usd: number) => formatMoney(usd, currency, rate);

    // a) Spend by provider — horizontal bar
    const provAgg = aggregateByProvider(entries, this.modelsData);
    const provTotal = provAgg.reduce((s, p) => s + p.cost, 0);
    // The label is just the name now: the renderer prints the value and the share itself, so
    // stuffing them into the label duplicated what the bar already says.
    const provBars = provAgg.map((p) => ({
      label: p.provider,
      value: p.cost * rate,
      color: colorFor(p.provider),
    }));
    const topProv = provAgg[0];
    const topPct =
      provTotal > 0 && topProv ? (topProv.cost / provTotal) * 100 : 0;
    const providerCell: CellContent = {
      kind: "bar-h",
      bars: provBars,
      valuePrefix: sym,
      ariaSummary: topProv
        ? `${topProv.provider} accounts for ${topPct.toFixed(0)}% of spend over ${rangeLabel}, ${money(topProv.cost)} of ${money(provTotal)} total.`
        : `No spend recorded over ${rangeLabel}.`,
    };

    // b) Spend by model over time — stacked bar
    const stacked = aggregateStackedByModel(entries, stackedDays, 5);
    const stackedTotal = stacked.series.reduce(
      (s, ser) => s + ser.values.reduce((a, b) => a + b, 0),
      0,
    );
    const stackedCell: CellContent = {
      kind: "stacked-bar",
      xLabels: stacked.xLabels,
      series: stacked.series.map((ser) => ({
        ...ser,
        values: ser.values.map((v) => v * rate),
      })),
      valuePrefix: sym,
      ariaSummary: `Daily spend across ${stacked.series.length} models over the last ${stackedDays} days, total ${money(stackedTotal)}.`,
    };

    // c) Tokens by model (input vs output)
    const tokAgg = aggregateTokensByModel(entries).slice(0, 6);
    const tokensCell: CellContent = {
      kind: "small-multiples",
      panels: tokAgg.map((t) => ({
        title: t.model,
        bars: [
          {
            label: "in",
            value: t.inputTokens,
            color: "var(--vscode-charts-blue)",
          },
          {
            label: "out",
            value: t.outputTokens,
            color: "var(--vscode-charts-orange)",
          },
        ],
      })),
      ariaSummary: `Input vs output tokens for ${tokAgg.length} models over ${rangeLabel}.`,
    };

    // d) Calls per model — donut
    const callsAgg = aggregateCallsByModel(entries);
    const callsTotal = callsAgg.reduce((s, c) => s + c.calls, 0);
    const donutSegs = callsAgg.slice(0, 6).map((c) => ({
      label: c.model,
      value: c.calls,
      color: colorFor(c.model),
    }));
    if (callsAgg.length > 6) {
      const otherCalls = callsAgg
        .slice(6)
        .reduce((s, c) => s + c.calls, 0);
      donutSegs.push({
        label: "other",
        value: otherCalls,
        color: DIM_FOREGROUND,
      });
    }
    const donutCell: CellContent = {
      kind: "donut",
      segments: donutSegs,
      centerLabel: `${callsTotal}`,
      ariaSummary: `${callsTotal} calls across ${callsAgg.length} models over ${rangeLabel}.`,
    };

    return {
      id: "consumption",
      title: "Consumption",
      content: [
        rangeSelector,
        { kind: "row", label: "Spend by provider" },
        providerCell,
        { kind: "row", label: `Spend by model — last ${stackedDays}d` },
        stackedCell,
        { kind: "row", label: "Tokens by model (input vs output)" },
        tokensCell,
        { kind: "row", label: "Calls per model" },
        donutCell,
      ],
    };
  }

  private benchmarksCell(): CellUpdate {
    const content: CellContent[] = [];
    // The live leaderboard first: the bundled file describes the benchmarks, but its SCORES age
    // immediately, and a stale ranking presented as current is the defect this fixes.
    const board = readLeaderboard();
    if (board) {
      content.push({ kind: "heading", text: "Model intelligence — Artificial Analysis" });
      content.push({
        kind: "row",
        label: board.isLive ? "live" : "stale",
        value: `${board.scores.length} models · ${describeBoardAge(board.ageSeconds)}`,
        dot: board.isLive ? "ok" : "missing",
        tooltip: "Fetched with your own ARTIFICIAL_ANALYSIS_API_KEY. Their index, their methodology.",
      });
      content.push({
        kind: "table",
        headers: ["Model", "Creator", "Index"],
        rows: board.scores.slice(0, 12).map((s) => [s.name, s.creator, s.intelligence.toFixed(1)]),
      });
    } else {
      content.push({
        kind: "row",
        label: "Model intelligence",
        value: "set ARTIFICIAL_ANALYSIS_API_KEY to fetch live scores (not redistributable, so they cannot ship)",
        dot: "missing",
      });
    }
    for (const cat of BENCHMARK_CATEGORIES) {
      const benches = this.benchmarksData.benchmarks.filter(
        (b) => b.category === cat.id,
      );
      if (!benches.length) continue;
      content.push({ kind: "heading", text: cat.label });
      for (const bench of benches) {
        // What the benchmark measures, and WHEN these scores are from. The date used to live in
        // the tooltip only, so a months-old leaderboard read as today's truth until you hovered.
        const { provenanceLabel } = require("./benchmarkTables");
        const asOf = provenanceLabel(bench.published?.retrieved);
        content.push({
          kind: "row",
          label: bench.name,
          value: `${bench.description} · ${asOf}`,
          tooltip: `${bench.url} · ${asOf}`,
        });
        const rows: string[][] = [];
        for (const e of (bench.published?.entries ?? []).slice(0, 5)) {
          rows.push([e.model_name, e.score.toFixed(3)]);
        }
        for (const [modelId, score] of Object.entries(bench.measured)) {
          rows.push([modelId, score.toFixed(3)]);
        }
        if (rows.length) {
          content.push({ kind: "table", headers: ["Best models", "Score"], rows });
        } else {
          content.push({
            kind: "row",
            label: "  ↳ scores",
            value: "no live scores yet — add this source's key in Configuration → Benchmark data",
          });
        }
      }
    }
    if (content.length === 0) {
      content.push({ kind: "empty", message: "No benchmark data available" });
    }
    return { id: "benchmarks", title: "Benchmarks by capability", content };
  }

  private recommendationsCell(): CellUpdate {
    const bench = this.benchmarksData.benchmarks.find(
      (b) => b.id === RECOMMENDATION_BENCHMARK,
    );
    if (!bench) {
      return {
        id: "recommendations",
        title: "Recommendations",
        content: [{ kind: "empty", message: "No benchmark data" }],
      };
    }
    const knownModels = new Set<string>();
    for (const info of Object.values(this.modelsData.providers)) {
      for (const name of Object.keys(info.models)) knownModels.add(name);
    }
    const top = bench.recommendations
      .filter((r) => knownModels.has(r.model_id))
      .slice(0, 3);
    if (!top.length) {
      return {
        id: "recommendations",
        title: "Recommendations",
        content: [{ kind: "empty", message: "No matching models in registry" }],
      };
    }
    const tableRows = top.map((r) => [
      r.model_id,
      r.score.toFixed(3),
      r.source,
      r.cost_per_million != null ? `$${r.cost_per_million.toFixed(2)}` : "—",
      r.quality_per_dollar != null ? r.quality_per_dollar.toFixed(3) : "—",
    ]);
    return {
      id: "recommendations",
      title: `Recommendations (${bench.name})`,
      content: [
        {
          kind: "table",
          headers: ["Model", "Score", "Source", "$/M", "Quality/$"],
          rows: tableRows,
        },
      ],
    };
  }

  /** Reload just the webview (re-fetches the built JS/CSS) — picks up panel changes WITHOUT a
   *  full window reload. Only the webview is rebuilt this way; extension-host code changes
   *  (dashboard.ts, extension.ts) still need a window reload. */
  reload(): void {
    if (this.disposed) return;
    this.panel.webview.html = this.getHtml(); // re-fetch assets; the webview's "ready" → refresh()
  }

  private getHtml(): string {
    const webview = this.panel.webview;
    const nonce = getNonce();
    // Cache-bust so reload() actually re-fetches a rebuilt bundle instead of a cached copy.
    const v = Date.now();
    const scriptUri = `${webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "out", "webview.js"),
    )}?v=${v}`;
    const styleUri = `${webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "out", "webview.css"),
    )}?v=${v}`;
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}' ${webview.cspSource};">
  <link rel="stylesheet" href="${styleUri}">
</head>
<body>
  <div id="root"></div>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}
