import * as vscode from "vscode";

import { ACTIVITY_SCHEME, activityPath, formatActivity, runIdFromPath } from "./activityDocument";
import { IO_INLINE, IO_SCHEME, ioFromPath } from "./ioDocument";
import { ChatViewProvider } from "./chatView";
import { REVEAL_COMMAND, REVEALED_KEY, shouldRevealOnce } from "./panelReveal";
import { AgentsProvider, type GroupBy } from "./agentsView";
import { DashboardPanel } from "./dashboard";
import { ScopeStore, setScopeStore } from "./scopeStore";
import { companyOf, definitionFile, readOrg, spawnArgs, spawnChoices } from "./org";
import { chooseModel, clearChoice, modelChosenFor } from "./agentModels";
import { knownModes, modeChoices } from "./permissionModes";
import {
  KeyManager,
  formatLabel,
  resolveCommand,
  ModelsData,
  SETTING_ENV_MAP,
  SETTING_TO_TASK,
} from "./shared";

const SETTING_SECTION = "interact";
const IS_SECRET_RE = /KEY|SECRET|TOKEN/i;

/** The autonomy new agents get in THIS workspace. Per workspace because "what may an agent do
 *  here" is a property of the repo you are in, not of the editor — and it APPLIES rather than
 *  merely pre-selecting, which is what `/permissions` promises when it sets it. */
const DEFAULT_MODE_KEY = "interact.agents.defaultPermissionMode";

interface ModelSettingItem extends vscode.QuickPickItem {
  settingKey: string;
}

// SETTING_ENV_MAP / SETTING_TO_TASK come from the shared schema (generated from settings.json) —
// the single source of truth, so the server's env can't drift from the settings UI (this is what
// previously sent debug.dir to the wrong env var and dropped desktop.nestedHeadless entirely).

function cfg() {
  return vscode.workspace.getConfiguration(SETTING_SECTION);
}

function buildEnv(
  keyManager: KeyManager,
  allEnvKeys: Set<string>,
  modelsData: ModelsData,
): Record<string, string> {
  const c = cfg();
  const env: Record<string, string> = {};

  for (const [k, v] of Object.entries(process.env)) {
    if (v !== undefined && !allEnvKeys.has(k)) {
      env[k] = v;
    }
  }

  for (const [settingKey, envKey] of Object.entries(SETTING_ENV_MAP)) {
    const value = c.get(settingKey);
    if (value === undefined || value === null || value === "") continue;
    env[envKey] =
      typeof value === "boolean" ? (value ? "true" : "false") : String(value);
  }

  for (const [k, v] of keyManager.entries()) {
    env[k] = v;
    const alias = modelsData.keyAliases?.[k];
    if (alias && !env[alias]) {
      env[alias] = v;
    }
  }

  // Ollama cloud: auto-set API base when key is present but base is not
  if (env["OLLAMA_API_KEY"] && !env["OLLAMA_API_BASE"]) {
    env["OLLAMA_API_BASE"] = "https://api.ollama.com";
  }

  // Determine which providers are fully configured
  const configuredProviders: string[] = [];
  for (const [provider, info] of Object.entries(modelsData.providers)) {
    if (info.envKeys.length === 0) continue;
    if (info.envKeys.every((k: string) => env[k])) {
      configuredProviders.push(provider);
    }
  }
  if (configuredProviders.length > 0) {
    env["INTERACT_CONFIGURED_PROVIDERS"] = configuredProviders.join(",");
  }

  env["INTERACT_MODELS_JSON"] = JSON.stringify(modelsData);

  // The catalog's `defaults` are NOT written into the environment. They used to be, and that one
  // block defeated model selection entirely: interact reads these vars as a user's explicit pin,
  // so every extension user looked pinned, the best-available walk never ran, and somebody with
  // only an OpenAI key got a Gemini id and an auth error. Leaving them unset lets the server rank
  // the catalog by capability and walk down to the first model actually configured — which is
  // also how a stronger model gets used the moment its key is added, with nothing to reconfigure.
  //
  // A pin the PERSON chose still arrives here through keyManager/settings and still wins.

  return env;
}

function providerOf(model: string, modelsData: ModelsData): string | undefined {
  for (const [provider, info] of Object.entries(modelsData.providers)) {
    if (model in info.models) return provider;
  }
}

async function ensureKeys(
  provider: string,
  modelsData: ModelsData,
  keyManager: KeyManager,
  emitter: vscode.EventEmitter<void>,
): Promise<boolean> {
  const info = modelsData.providers[provider];
  if (!info) return true;
  const missing = keyManager.missingKeys(info.envKeys);
  for (const key of missing) {
    if (process.env[key]) {
      const use = await vscode.window.showInformationMessage(
        `Found ${key} in your environment. Use it?`,
        "Yes",
        "No",
      );
      if (use === "Yes") {
        await keyManager.set(key, process.env[key]!);
        emitter.fire();
        continue;
      }
    }
    const value = await vscode.window.showInputBox({
      prompt: `Enter your ${key}`,
      password: IS_SECRET_RE.test(key),
      ignoreFocusOut: true,
    });
    if (!value) return false;
    await keyManager.set(key, value);
    emitter.fire();
  }
  return true;
}

async function selectModel(
  modelsData: ModelsData,
  keyManager: KeyManager,
  emitter: vscode.EventEmitter<void>,
): Promise<void> {
  const modelKeys = Object.keys(SETTING_TO_TASK);
  if (!modelKeys.length) return;

  let settingKey: string;
  if (modelKeys.length === 1) {
    settingKey = modelKeys[0];
  } else {
    const picked = await vscode.window.showQuickPick<ModelSettingItem>(
      modelKeys.map((k) => ({
        label: formatLabel(k),
        description: modelsData.taskDescriptions?.[SETTING_TO_TASK[k]] ?? "",
        settingKey: k,
      })),
      { placeHolder: "Which model to configure?" },
    );
    if (!picked) return;
    settingKey = picked.settingKey;
  }

  const task = SETTING_TO_TASK[settingKey];
  const recs = task ? (modelsData.recommendations?.[task] ?? []) : [];
  const recSet = new Set(recs);

  const items: vscode.QuickPickItem[] = [];

  const currentModel = cfg().get<string>(settingKey) || "";
  if (currentModel) {
    items.push({
      label: "Current",
      kind: vscode.QuickPickItemKind.Separator,
    });
    items.push({
      label: currentModel,
      description: "currently selected",
    });
  }

  if (recs.length) {
    items.push({
      label: "Recommended",
      kind: vscode.QuickPickItemKind.Separator,
    });
    for (const [i, model] of recs.entries()) {
      if (model === currentModel) continue;
      const provider = providerOf(model, modelsData);
      const meta = provider
        ? modelsData.providers[provider]?.models[model]
        : undefined;
      let desc = `#${i + 1}`;
      if (meta?.intelligence_score)
        desc += ` | Score: ${meta.intelligence_score}`;
      if (meta?.input_cost_per_million) {
        desc += ` | $${meta.input_cost_per_million}/M in`;
      }
      items.push({
        label: model,
        description: desc,
      });
    }
  }

  const allModels: string[] = [];
  for (const [, info] of Object.entries(modelsData.providers)) {
    for (const name of Object.keys(info.models)) {
      if (recSet.has(name)) continue;
      allModels.push(name);
    }
  }

  // Group remaining models by provider
  const byProvider: Record<string, string[]> = {};
  for (const name of allModels) {
    const prov = providerOf(name, modelsData) ?? "other";
    (byProvider[prov] ??= []).push(name);
  }

  for (const prov of Object.keys(byProvider).sort()) {
    byProvider[prov].sort();
    items.push({
      label: prov,
      kind: vscode.QuickPickItemKind.Separator,
    });
    for (const name of byProvider[prov]) {
      const meta = modelsData.providers[prov]?.models[name];
      let desc = "";
      if (meta?.intelligence_score) desc += `Score: ${meta.intelligence_score}`;
      if (meta?.input_cost_per_million) {
        desc += desc ? " | " : "";
        desc += `$${meta.input_cost_per_million}/M in`;
      }
      items.push({ label: name, description: desc || undefined });
    }
  }

  if (!items.length) {
    vscode.window.showWarningMessage(
      "No models available. Run generate-models script.",
    );
    return;
  }

  const picked = await vscode.window.showQuickPick(items, {
    placeHolder: `Select ${formatLabel(settingKey).toLowerCase()}`,
    matchOnDescription: true,
  });

  if (!picked) return;

  await cfg().update(
    settingKey,
    picked.label,
    vscode.ConfigurationTarget.Global,
  );

  const provider = providerOf(picked.label, modelsData);
  if (provider) {
    await ensureKeys(provider, modelsData, keyManager, emitter);
  }
}

async function manageApiKeys(
  keyManager: KeyManager,
  modelsData: ModelsData,
  emitter: vscode.EventEmitter<void>,
): Promise<void> {
  const entries = keyManager.entries();
  const items: vscode.QuickPickItem[] = [];

  for (const [key, value] of entries) {
    const masked =
      value.length > 8 ? value.slice(0, 4) + "..." + value.slice(-4) : "****";
    items.push({ label: key, description: masked });
  }
  items.push({ label: "$(add) Add new API key", description: "" });

  const picked = await vscode.window.showQuickPick(items, {
    placeHolder: "Manage API keys",
  });
  if (!picked) return;

  if (picked.label.startsWith("$(add)")) {
    const allKeys = new Set<string>();
    for (const info of Object.values(modelsData.providers)) {
      for (const k of info.envKeys) allKeys.add(k);
    }
    const unconfigured = [...allKeys].filter((k) => !keyManager.get(k)).sort();
    if (!unconfigured.length) {
      vscode.window.showInformationMessage(
        "All provider API keys are already configured.",
      );
      return;
    }
    const keyName = await vscode.window.showQuickPick(unconfigured, {
      placeHolder: "Which API key?",
    });
    if (!keyName) return;
    const value = await vscode.window.showInputBox({
      prompt: `Enter ${keyName}`,
      password: IS_SECRET_RE.test(keyName),
      ignoreFocusOut: true,
    });
    if (value) {
      await keyManager.set(keyName, value);
      emitter.fire();
    }
    return;
  }

  const action = await vscode.window.showQuickPick(
    [{ label: "Update" }, { label: "Remove" }],
    { placeHolder: picked.label },
  );
  if (!action) return;
  if (action.label === "Remove") {
    await keyManager.remove(picked.label);
    emitter.fire();
    vscode.window.showInformationMessage(`Removed ${picked.label}`);
  } else {
    const value = await vscode.window.showInputBox({
      prompt: `Enter new value for ${picked.label}`,
      password: IS_SECRET_RE.test(picked.label),
      ignoreFocusOut: true,
    });
    if (value) {
      await keyManager.set(picked.label, value);
      emitter.fire();
    }
  }
}

/** Repaint the room's roster. Lazily imported: the workplace pulls in the art bundle, and a
 *  window that never opens the room should not pay for it. */
function refreshWorkplace(): void {
  void import("./workplacePanel").then((m) => m.WorkplacePanel.refreshIfOpen()).catch(() => {});
}

export async function activate(
  context: vscode.ExtensionContext,
): Promise<void> {
  let modelsData: ModelsData = { providers: {} };
  try {
    const loaded = require("./models.json");
    if (loaded?.providers) modelsData = loaded;
  } catch {}

  const allEnvKeys = new Set<string>();
  for (const info of Object.values(modelsData.providers)) {
    for (const k of info.envKeys) allEnvKeys.add(k);
  }

  const keyManager = new KeyManager();
  await keyManager.loadAll([...allEnvKeys]);

  const log = vscode.window.createOutputChannel("Interact");

  // Show the panel once, the first time the extension runs. VS Code registers a newly-contributed
  // container HIDDEN, so without this it sits in the secondary side bar with no icon to click and
  // nothing to hint it is there. Once only — reopening it every window would be a hijack.
  //
  // Runs after the tree provider is registered (else the revealed view has no data source), and
  // records success only once the reveal actually happened: marking it first would mean a single
  // failed call suppressed the reveal in every future window, permanently and invisibly.
  async function revealAgentsPanelOnce(): Promise<void> {
    if (!shouldRevealOnce(context.globalState)) return;
    try {
      await vscode.commands.executeCommand(REVEAL_COMMAND);
      await context.globalState.update(REVEALED_KEY, true);
    } catch (err) {
      log.appendLine(`could not reveal the Agents panel: ${err}`);
    }
  }


  // The Agents sidebar — the panel you click, in the SECONDARY side bar (right), beside Claude
  // Code / Codex / Gemini, where a chat panel belongs. `viewsContainers.secondarySidebar` is what
  // puts it there; the manifest's `engines.vscode` floor is past the build that added it.

  // One workspace scope, shared by every view, so the tree and the building can never disagree
  // about which team you are looking at. Defaults to the folder you have open.
  const scope = new ScopeStore(context.globalState, log);
  const agentsProvider = new AgentsProvider(context.globalState);
  agentsProvider.scopeStore = scope;
  setScopeStore(scope);
  // The chat surface, under the agent list in the same side-bar container: the list says what is
  // running, this is where you talk to it.
  const chatProvider = new ChatViewProvider(log);
  // Clicking somebody in the rail aims the chat at them, exactly as clicking a tree row does —
  // one behaviour, so the two surfaces cannot teach different things.

  // The way back out of a conversation. Clearing the context key un-hides the roster views, and
  // focusing the rail puts you where you were — so "open a conversation" and "see the team" are
  // one column used two ways rather than three panes fighting over it.
  context.subscriptions.push(
    // Choosing what runs on what. The company file DECLARES a model per agent, but it is generated
    // from the prompt repo — so a choice made here is stored beside interact's own state, where no
    // generator owns it, and shown as overriding rather than replacing the declaration.
    // "See their instructions" opened the TRANSCRIPT — a label that lied, caught by the sweep.
    // This opens the definition file itself, resolved against the prompt repo's real location.
    vscode.commands.registerCommand("interact.agents.definition", (arg?: { run?: { agent?: string | null; definition_path?: string | null } }) => {
      const run = arg?.run;
      const path = run?.definition_path
        ?? (run?.agent ? definitionFile(run.agent, readOrg()) : null);
      if (path) void vscode.window.showTextDocument(vscode.Uri.file(path));
      else void vscode.window.showInformationMessage("This run has no definition file — it is a bare session.");
    }),
    // The middle depth: an agent and the tasks it was given.
    vscode.commands.registerCommand("interact.agents.agent", async (arg?: string | { run?: { agent?: string } }) => {
      let agent = typeof arg === "string" ? arg : arg?.run?.agent;
      if (!agent) {
        // Called with nothing: offer the whole company. Until now the only door into an agent was a
        // role chip on one of its OWN runs, so a teammate that had never been asked for anything was
        // unreachable — declared in the company file, present in the room, and impossible to open.
        const org = readOrg();
        const picked = await vscode.window.showQuickPick(
          (org?.agents ?? []).map((a) => ({
            label: a.name,
            description: a.title ?? "",
            detail: [a.department, a.model].filter(Boolean).join(" · "),
          })),
          { title: "Which agent?", placeHolder: "Every agent in the company, whether or not it has run" },
        );
        agent = picked?.label;
      }
      if (agent) chatProvider.showAgent(agent);
    }),
    vscode.commands.registerCommand("interact.agents.model", async (arg?: string | { run?: { agent?: string } }) => {
      const org = readOrg();
      const named = typeof arg === "string" ? arg : arg?.run?.agent ?? undefined;
      const agent = named ?? (await vscode.window.showQuickPick(
        org?.agents.map((a) => ({ label: a.name, description: a.title ?? "" })) ?? [],
        { title: "Which agent?", placeHolder: "Pick the agent whose model you want to change" },
      ))?.label;
      if (!agent) return;

      const declared = org?.agents.find((a) => a.name === agent)?.model ?? "inherit";
      const current = modelChosenFor(agent);
      // Handed a PROMISE on purpose: the first open can spend fifteen seconds fetching the model
      // catalog, and VS Code renders its own loading state for a pending item list. Awaiting first
      // showed nothing at all for that whole window, which reads as a dead control.
      const items: Promise<vscode.QuickPickItem[]> = (async () => {
        const { loadCatalog } = await import("./catalog");
        const cat = await loadCatalog().catch(() => null);
        return [
          { label: "$(discard) Use the company file", description: `declared: ${declared}`,
            detail: current ? `clears your choice of ${current}` : "no choice is set" },
          ...(cat?.models ?? []).map((m) => ({
            label: m.id,
            description: m.id === current ? "current choice" : m.id === declared ? "declared" : "",
          })),
        ];
      })();
      const pick = await vscode.window.showQuickPick(items, {
        title: `Model for ${agent}`,
        placeHolder: current ? `currently ${current}` : `currently ${declared} (from the company file)`,
      });
      if (!pick) return;
      if (pick.label.startsWith("$(discard)")) {
        clearChoice(agent);
        void vscode.window.showInformationMessage(`${agent} follows the company file again (${declared}).`);
      } else if (chooseModel(agent, pick.label)) {
        void vscode.window.showInformationMessage(`${agent} will run on ${pick.label}.`);
      } else {
        void vscode.window.showWarningMessage(`${pick.label} is not a model id interact will store.`);
      }
      refreshWorkplace();
      // And the panel you are looking at, or the override you just set stays invisible until you
      // navigate away and back — which defeats the reason it is rendered at all.
      chatProvider.repaintAgent(agent);
    }),
    vscode.commands.registerCommand("interact.agents.backToTeam", () => {
      void vscode.commands.executeCommand("setContext", "interact.inConversation", false);
      // Clear the panel's own depth and repaint it. Flipping the key alone left every "back"
      // control inert once the roster moved out of the side bar and the key stopped gating
      // anything — a context key is not navigation.
      chatProvider.backToTeam();
      // The team lives in the big panel now, so this reveals the room rather than a side-bar view.
      void vscode.commands.executeCommand("interact.agents.team");
    }),
  );
  context.subscriptions.push(
    agentsProvider,
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewId, chatProvider),
    // The rail: the panel's own chrome, VISIBLE AT REST. A TreeView's title actions are hidden
    // until the pointer enters the header and clipped with no overflow menu, which is why the
    // team view could not be reached at all — measured on a real editor, not inferred. Clicking
    // somebody here aims the chat at them, exactly as the tree does.
    // Picking an agent aims the chat at it — the reason the two views sit together.
    // Switching which agent you are reading meant leaving the chat for the tree, which is half of
    // "i can't control everything from there". Scoped to the current workspace, so the list is the
    // team you are actually looking at.
    vscode.commands.registerCommand("interact.agents.pick", async () => {
      const runs = scope.runs();
      if (runs.length === 0) {
        void vscode.window.showInformationMessage(`No agents in ${scope.describe()}.`);
        return;
      }
      const chosen = await vscode.window.showQuickPick(
        runs.map((r) => ({
          label: r.name,
          description: r.status,
          detail: [r.project, r.agent, r.model].filter(Boolean).join(" · "),
          runId: r.run_id,
        })),
        { title: `Read an agent — ${scope.describe()}`, matchOnDetail: true },
      );
      if (chosen) chatProvider.show(chosen.runId);
    }),
    vscode.commands.registerCommand("interact.agents.chat", (arg?: string | { run?: { run_id: string } }) => {
      const runId = typeof arg === "string" ? arg : arg?.run?.run_id;
      if (runId) chatProvider.show(runId);
    }),
    vscode.workspace.registerTextDocumentContentProvider(ACTIVITY_SCHEME, {
      async provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
        const { readAgentActivity } = await import("./agents");
        return formatActivity(readAgentActivity(runIdFromPath(uri.path), 200));
      },
    }),
    // One tool call's WHOLE input or output. The transcript's rows are summaries by design;
    // this serves the unclipped payload out of the raw stream (or, for one of your own
    // sessions, the provider's transcript), keyed by the vendor's tool id.
    vscode.workspace.registerTextDocumentContentProvider(IO_SCHEME, {
      async provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
        const parsed = ioFromPath(uri.path);
        if (!parsed) return "(unrecognised tool-call reference)";
        // Banked text first: an unstamped call's stored half, handed over by the webview.
        const banked = IO_INLINE.get(parsed.toolId);
        if (banked !== undefined) return banked;
        const { readAgentRuns, rawEventsPath } = await import("./agents");
        const { foreignTranscriptPath, fullToolIO } = await import("./foreignSession");
        const run = readAgentRuns().find((r) => r.run_id === parsed.runId)
          ?? scope.runs().find((r) => r.run_id === parsed.runId);
        const file = run?.status === "foreign"
          ? foreignTranscriptPath(run) : rawEventsPath(parsed.runId);
        const full = file ? fullToolIO(file, parsed.toolId, parsed.side) : null;
        return full
          ?? "(the raw stream no longer holds this call — it may predate the id stamping)";
      },
    }),
    vscode.commands.registerCommand("interact.agents.refresh", () => agentsProvider.refresh()),
    // "i have agents in the 'sheets' folder elsewhere, and i can't change and see how they work"
    // One brief to everyone working. interact supervises a team, so this is a capability the
    // single-agent panels cannot have — and the reason it asks first is that it reaches every
    // running agent at once, which is not something to discover by mistyping.
    vscode.commands.registerCommand("interact.agents.broadcast", async () => {
      const running = scope.runs().filter((r) => r.status === "running" && !r.foreign);
      if (running.length === 0) {
        void vscode.window.showInformationMessage(`Nobody is running in ${scope.describe()}.`);
        return;
      }
      const text = await vscode.window.showInputBox({
        title: `Message ${running.length} running agent${running.length > 1 ? "s" : ""}`,
        prompt: running.map((r) => r.name).join(", "),
        placeHolder: "e.g. the API changed — re-read src/api.ts before continuing",
        ignoreFocusOut: true,
      });
      if (!text) return;
      const confirm = await vscode.window.showWarningMessage(
        `Send to all ${running.length}?`, { modal: true, detail: running.map((r) => r.name).join(", ") },
        "Send",
      );
      if (confirm !== "Send") return;
      const { execFile } = await import("child_process");
      let failed = 0;
      await Promise.all(running.map((r) => new Promise<void>((done) => {
        execFile("interact", ["agents", "send", r.run_id, text], (err) => {
          if (err) failed++;
          done();
        });
      })));
      void vscode.window.showInformationMessage(
        failed
          ? `Sent to ${running.length - failed} of ${running.length} — ${failed} could not be reached.`
          : `Sent to all ${running.length}.`,
      );
    }),
    vscode.commands.registerCommand("interact.agents.workspace", async () => {
      if (await scope.pick()) {
        agentsProvider.refresh();
        refreshWorkplace();
      }
    }),
    scope.onDidChange(() => agentsProvider.refresh()),
    // Starting an agent from the panel. Without this the panel could only WATCH — you had to
    // leave it for a terminal to put anyone to work, which is not a team you manage.
    /* A NEW SESSION, with no questions but the one that matters.
     *
     *  "I should always be able to create a new session, and when i click on a session, then
     *  inside i see everything (just like in claude code)." Starting work meant picking a
     *  definition out of forty first — a staffing decision, at the moment you have a task. The
     *  entry agent (the company's coordinator: what the org file calls `main`) takes it, and it
     *  is the one that puts the specialists to work — so the session begins where Claude Code's
     *  begins, and the roster stays for when you deliberately want one person.
     */
    vscode.commands.registerCommand("interact.agents.newSession", async () => {
      const { execFile } = await import("child_process");
      const company = companyOf(readOrg());
      const entry = company?.coordinator.id ?? "main";
      const task = await vscode.window.showInputBox({
        title: "New session",
        prompt: "What do you want done? The session's agent can put others to work.",
        placeHolder: "e.g. find why the panel renders twice on a cold open",
        ignoreFocusOut: true,
      });
      if (!task) return;
      const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
      const args = spawnArgs({
        task, agent: entry, cwd, org: readOrg(),
        // The workspace's own autonomy setting applies, exactly as it does for a picked agent —
        // a new session must not be a back door around `/permissions`.
        permissionMode: context.workspaceState.get<string | null>(DEFAULT_MODE_KEY, null),
        model: modelChosenFor(entry),
      });
      execFile("interact", args, (err, stdout, stderr) => {
        const said = (stdout || stderr || "").trim();
        if (err) {
          void vscode.window.showErrorMessage(`Interact: could not start a session — ${said || err}`);
          return;
        }
        agentsProvider.refresh();
        refreshWorkplace();
        // Straight INTO it: a new session you have to go and find is not a new session.
        const id = said.split(/\s+/).find((w) => w.length >= 8) ?? said.slice(0, 36);
        if (id) chatProvider.show(id);
      });
    }),
    vscode.commands.registerCommand("interact.agents.spawn", async () => {
      const { execFile } = await import("child_process");
      // A machine-readable list, not the human providers table: scraping that would empty the
      // picker the day its wording changed.
      const definitions = await new Promise<string[]>((resolve) => {
        execFile("interact", ["agents", "definitions"], (err, stdout) => {
          resolve(err ? [] : stdout.split("\n").map((n) => n.trim()).filter(Boolean));
        });
      });
      // Presented as the COMPANY, not a directory listing: what the person does, which
      // department they sit in, and where they can actually run. The definitions list stays the
      // ground truth for what is runnable, so an agent the org file omits is still offered.
      const picked = await vscode.window.showQuickPick(
        spawnChoices(definitions, readOrg()),
        { title: "Who should take this?", placeHolder: "the definition it will run as",
          matchOnDetail: true },
      );
      if (!picked) return;
      const task = await vscode.window.showInputBox({
        title: `Brief for ${picked.label}`,
        prompt: "It cannot ask you a follow-up — write a complete brief.",
        placeHolder: "e.g. review the uncommitted diff for correctness",
        ignoreFocusOut: true,
      });
      if (!task) return;
      // How much this one may do on its own — the decision that makes a heterogeneous team
      // possible rather than N copies of the same autonomy. Read from the CLI, never hardcoded:
      // two copies of a vendor's flag values drift, and it is always this copy that drifts.
      const modes = await knownModes();
      // The workspace default — what `/permissions` set. It APPLIES; it does not merely float to
      // the top of the picker. Those were two meanings of one setting in two files, and the
      // command's own confirmation ("New agents here start with X") promised the first while the
      // spawn path did the second: dismiss the picker and you silently got the CLI's default.
      const workspaceDefault = context.workspaceState.get<string | null>(DEFAULT_MODE_KEY, null);
      let permissionMode: string | null = workspaceDefault;
      if (modes.length) {
        const mode = await vscode.window.showQuickPick(modeChoices(modes, workspaceDefault), {
          title: `How much may ${picked.label} do on its own?`,
          placeHolder: workspaceDefault
            ? `dismiss to keep this workspace's setting (${workspaceDefault})`
            : "dismiss to leave your CLI's own setting alone",
          matchOnDetail: true,
        });
        // Escape CANCELS. It used to fall through and spawn with the default — a paid process
        // launched from the cancel gesture, observed live by an independent sweep. The default is
        // an explicit row in the picker ("Your CLI's default"), so nothing is lost by making the
        // dismiss gesture mean what it means everywhere else.
        if (mode === undefined) return;
        permissionMode = mode.id;
        if (mode.id) await context.workspaceState.update(DEFAULT_MODE_KEY, mode.id);
      }
      const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
      const args = spawnArgs({
        task, agent: picked.label, cwd, org: readOrg(), permissionMode,
        // Whatever you chose for this agent in the editor; absent, the company file decides.
        model: modelChosenFor(picked.label),
      });
      execFile("interact", args, (err, stdout, stderr) => {
        const said = (stdout || stderr || "").trim();
        if (err) {
          void vscode.window.showErrorMessage(`Interact: could not start ${picked.label} — ${said || err}`);
          return;
        }
        void vscode.window.showInformationMessage(`${picked.label} is working (${said.slice(0, 8)}).`);
        agentsProvider.refresh();
        refreshWorkplace();
      });
    }),
    // The autonomy a new agent gets here, set WITHOUT having to spawn one to be asked. A
    // workspace-wide default is the setting people actually want: "in this repo, agents plan
    // first" is a property of the repo, and choosing it per spawn is how you end up not choosing.
    vscode.commands.registerCommand("interact.agents.permissions", async () => {
      const modes = await knownModes();
      if (!modes.length) {
        void vscode.window.showInformationMessage(
          "Interact: this agent CLI does not expose a permission setting we have verified.");
        return;
      }
      const current = context.workspaceState.get<string | null>(DEFAULT_MODE_KEY, null);
      const picked = await vscode.window.showQuickPick(modeChoices(modes, current), {
        title: "How much may agents started here do on their own?",
        placeHolder: current ? `currently: ${current}` : "currently: your CLI's own setting",
        matchOnDetail: true,
      });
      if (!picked) return;
      await context.workspaceState.update(DEFAULT_MODE_KEY, picked.id);
      void vscode.window.showInformationMessage(
        picked.id
          ? `New agents here start with: ${picked.label.replace(/^\$\([^)]+\)\s*/, "")}.`
          : "New agents here use your CLI's own setting.");
    }),
    // The log the extension already writes, made reachable from the panel rather than only from
    // the Output dropdown — a place people look only after being told it exists.
    vscode.commands.registerCommand("interact.showLogs", () => log.show(true)),
    // The team as a workplace: who is here, and what room the work has them in.
    vscode.commands.registerCommand("interact.agents.team", async () => {
      const { WorkplacePanel } = await import("./workplacePanel");
      WorkplacePanel.show(log);
    }),
    vscode.commands.registerCommand("interact.agents.sequence", async () => {
      const { SequencePanel } = await import("./sequencePanel");
      SequencePanel.show();
    }),
    // The manifest already puts the panel in the secondary side bar; what it cannot do is make it
    // VISIBLE — VS Code registers a new container hidden, so there is no icon to click until
    // something reveals it. This is that something, and it is also how you get the panel back
    // after closing it.
    vscode.commands.registerCommand("interact.agents.show", () =>
      vscode.commands.executeCommand(REVEAL_COMMAND),
    ),
    // Talking BACK to an agent, not only watching it. The agent resumes its own session, so it
    // answers with everything it has already done still in context, and the reply lands in the
    // same transcript the conversation view shows.
    vscode.commands.registerCommand("interact.agents.send", async (node?: { run?: { run_id: string; name: string } }) => {
      const run = node?.run;
      if (!run) return;
      const message = await vscode.window.showInputBox({
        title: `Message ${run.name}`,
        prompt: "It answers with its full context intact — write a complete request.",
        placeHolder: "e.g. also check the error paths",
        ignoreFocusOut: true,
      });
      if (!message) return;
      const { execFile } = await import("child_process");
      execFile("interact", ["agents", "send", run.run_id, message], (err, stdout, stderr) => {
        const said = (stdout || stderr || "").trim();
        if (err || said.startsWith("ERROR")) {
          vscode.window.showErrorMessage(said || `Could not reach ${run.name}.`);
          return;
        }
        vscode.window.showInformationMessage(said || `Sent to ${run.name}.`);
        agentsProvider.refresh();
        refreshWorkplace();
      });
    }),
    vscode.commands.registerCommand("interact.agents.openConversation", async (arg?: string | { run?: { run_id: string } }) => {
      const runId = typeof arg === "string" ? arg : arg?.run?.run_id;
      if (!runId) return;
      const { ConversationPanel } = await import("./conversation");
      ConversationPanel.show(runId);
    }),
    vscode.commands.registerCommand("interact.agents.groupBy", async () => {
      const pick = await vscode.window.showQuickPick(
        [
          { label: "Project", value: "project", description: "the directory each agent works in" },
          { label: "Provider", value: "provider", description: "claude, codex, …" },
          { label: "Model", value: "model" },
          { label: "Flat", value: "flat", description: "no grouping" },
        ],
        { title: "Group agents by", placeHolder: `currently: ${agentsProvider.groupBy}` },
      );
      if (pick) await agentsProvider.setGroupBy(pick.value as GroupBy);
    }),
    vscode.commands.registerCommand("interact.agents.stop", async (node?: { run?: { run_id: string; name: string } }) => {
      const run = node?.run;
      if (!run) return;
      // Stopping is Python's job (it owns the process group); the extension only asks.
      const { execFile } = await import("child_process");
      execFile("interact", ["agents", "stop", run.run_id], (err) => {
        if (err) vscode.window.showErrorMessage(`Could not stop ${run.name}: ${err.message}`);
        agentsProvider.refresh();
        refreshWorkplace();
      });
    }),
    vscode.commands.registerCommand("interact.agents.showEvents", async (node?: { run?: { run_id: string; name: string } }) => {
      const run = node?.run;
      if (!run) return;
      // Served by our own scheme, so it opens READ-ONLY. An untitled document would be dirty,
      // and closing it would ask the user to save a log they never wrote.
      const uri = vscode.Uri.from({
        scheme: ACTIVITY_SCHEME,
        path: activityPath(run.run_id, run.name),
      });
      const doc = await vscode.workspace.openTextDocument(uri);
      await vscode.languages.setTextDocumentLanguage(doc, "log");
      await vscode.window.showTextDocument(doc, { preview: true });
    }),
  );

  // Now that the view has a data provider, it is safe to show — a revealed view with no
  // provider renders as empty and reads like a broken panel.
  void revealAgentsPanelOnce();
  context.subscriptions.push(log);

  // No `secrets.onDidChange` listener: KeyManager stores keys in ~/.interact/config.env (the
  // file the CLI + server share), not SecretStorage, so nothing ever writes a secret for that
  // event to fire on. Key edits refresh the panel through KeyManager.set/remove directly.
  const emitter = new vscode.EventEmitter<void>();
  context.subscriptions.push(emitter);

  try {
    const serverDef = (vscode.lm as any).registerMcpServerDefinitionProvider(
      "interact",
      {
        provideMcpServerDefinitions() {
          const [cmd, args] = resolveCommand(log);
          const env = buildEnv(keyManager, allEnvKeys, modelsData);
          log.appendLine(`Starting: ${cmd} ${args.join(" ")}`);
          return [
            new (vscode as any).McpStdioServerDefinition(
              "Interact",
              cmd,
              args,
              env,
            ),
          ];
        },
        onDidChangeMcpServerDefinitions: emitter.event,
      },
    );
    context.subscriptions.push(serverDef);
    log.appendLine("MCP server definition registered");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    log.appendLine(`MCP registration failed: ${msg}`);
    vscode.window.showWarningMessage(
      `Interact: MCP server registration failed — ${msg}`,
    );
  }

  let benchmarksData: unknown = { benchmarks: [] };
  try {
    // The bundled file is baked at BUILD time, so its scores can never change once packaged.
    // Whatever Python has fetched since wins, per benchmark.
    const { mergeLiveTables, readLiveTables } = require("./benchmarkTables");
    benchmarksData = mergeLiveTables(require("./benchmarks.json"), readLiveTables());
  } catch {}

  const statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100,
  );
  statusBar.text = "$(eye) Interact";
  statusBar.tooltip = "Open Interact dashboard";
  statusBar.command = "interact.openDashboard";
  statusBar.show();
  context.subscriptions.push(statusBar);

  context.subscriptions.push(
    DashboardPanel.registerSerializer(
      context.extensionUri,
      keyManager,
      modelsData,
      benchmarksData,
      emitter,
    ),
  );

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (!e.affectsConfiguration(SETTING_SECTION)) return;
      emitter.fire();
      DashboardPanel.refreshIfOpen();
      const c = cfg();
      for (const key of Object.keys(SETTING_TO_TASK)) {
        const val = c.get<string>(key);
        if (val && !providerOf(val, modelsData)) {
          vscode.window.showWarningMessage(
            `Model '${val}' not recognized. Use the "Interact: Select Model" command to pick from available vision models.`,
          );
        }
      }
    }),
    vscode.commands.registerCommand("interact.selectModel", () =>
      selectModel(modelsData, keyManager, emitter),
    ),
    vscode.commands.registerCommand("interact.manageApiKeys", () =>
      manageApiKeys(keyManager, modelsData, emitter),
    ),
    vscode.commands.registerCommand("interact.openDashboard", () =>
      DashboardPanel.createOrShow(
        context.extensionUri,
        keyManager,
        modelsData,
        benchmarksData,
        emitter,
      ),
    ),
    vscode.commands.registerCommand("interact.reloadPanel", () =>
      DashboardPanel.instance?.reload(),
    ),
  );
}

export function deactivate(): void {}
