/** Process-bound acceptance for the extension-owned newline-JSON conversation client. */
import { strict as assert } from "node:assert";
import { createRequire } from "node:module";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const require_ = createRequire(import.meta.url);
const {
  CONVERSATION_SHUTDOWN_GRACE_MS,
  conversationHostArgs,
  createConversationClient,
  usesConversationTransport,
} = require_("../out/conversationClient.js");

const fakeHost = path.join(
  path.dirname(fileURLToPath(import.meta.url)), "..", "test", "fixtures", "conversationFakeHost.ts",
);

function fake(mode = "healthy") {
  return {
    command: process.execPath,
    args: ["--experimental-strip-types", fakeHost],
    cwd: path.dirname(fakeHost),
    env: { ...process.env, INTERACT_FAKE_CONVERSATION_MODE: mode },
  };
}

test("the host command is workspace-bound and only conversation runs use its continuation", () => {
  // The extension has two delivery contracts: historical process runs retain the established CLI
  // send path, while provider conversations stay on their one typed host process.
  assert.deepEqual(
    conversationHostArgs(["run", "interact", "mcp"], "/workspace/project"),
    ["run", "interact", "agents", "console", "--workspace-root", "/workspace/project"],
  );
  for (const [kind, expected] of [
    [undefined, false],
    ["process", false],
    ["conversation", true],
    ["provider_child", false],
  ] as const) {
    assert.equal(usesConversationTransport({
      run_id: "run",
      provider: "provider-a",
      name: "agent",
      kind,
    }), expected, String(kind));
  }
});

test("one stdio process negotiates, catalogs, starts, streams, resumes, interacts and cancels", async () => {
  // No unit mock covers framing, process lifetime and an event interleaved with responses.
  const streamed: string[] = [];
  const deliveryOrder: string[] = [];
  const states: string[] = [];
  let received: (() => void) | undefined;
  const streamedEvent = new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("event timeout")), 1000);
    received = () => { clearTimeout(timer); resolve(); };
  });
  const client = createConversationClient(fake(), {
    onState: (state) => states.push(state),
    onEvent: (_run, event) => {
      deliveryOrder.push(`event:${event.kind}`);
      streamed.push(event.text);
      if (streamed.length === 2) received?.();
    },
  });
  try {
    const catalog = await client.catalog();
    assert.equal(catalog.routes[0].connection, "local_session");
    assert.equal(catalog.routes[0].charge_path, "subscription_quota");

    const started = await client.start({
      route_id: "session-route",
      prompt: "Inspect the workspace",
      selection: { model: "example-model" },
      workspace_root: path.dirname(fakeHost),
    });
    deliveryOrder.push("start-continuation");
    assert.equal(started.run_id, "root-run");
    await streamedEvent;
    assert.equal(deliveryOrder[0], "start-continuation",
      "the consumer must install the returned run before any same-chunk event callback observes it");
    assert.deepEqual(streamed, [
      "streamed café answer",
      "child event with the same provider-local id",
    ], "UTF-8 framing survives split bytes; dedupe is scoped by run id plus event id");

    assert.equal((await client.send("root-run", "continue")).run_id, "root-run");
    assert.equal((await client.interact("root-run", {
      interaction_id: "interaction-1", values: { decision: "decline" },
    })).run_id, "root-run");
    assert.equal((await client.cancel("root-run")).status, "stopped");
    assert.equal(client.state(), "ready");
    assert.deepEqual(states, ["connecting", "ready"], "each client transition is emitted once");

    // A response and its first event may occupy one stdout chunk. This stays in the process test
    // because only byte framing plus Promise scheduling can reproduce the consumer-order race.
    const sameChunkOrder: string[] = [];
    let terminalReceived: (() => void) | undefined;
    const terminalEvent = new Promise<void>((resolve) => { terminalReceived = resolve; });
    const sameChunk = createConversationClient(fake("same_chunk_terminal"), {
      onEvent: () => { sameChunkOrder.push("event"); terminalReceived?.(); },
    });
    try {
      await sameChunk.catalog();
      await sameChunk.start({
        route_id: "session-route",
        prompt: "complete immediately",
        selection: { model: "example-model" },
        workspace_root: path.dirname(fakeHost),
      });
      sameChunkOrder.push("start-continuation");
      await terminalEvent;
      assert.deepEqual(sameChunkOrder, ["start-continuation", "event"],
        "the returned run is installed before a same-chunk terminal event reaches the view");
    } finally {
      sameChunk.dispose();
    }
  } finally {
    client.dispose();
  }
});

test("dispose and protocol failure close stdin long enough for host cleanup", async () => {
  // The Python host owns provider subprocesses. Abruptly killing it on webview shutdown bypasses
  // its EOF cleanup and can orphan the provider session after the extension window is gone.
  assert.ok(CONVERSATION_SHUTDOWN_GRACE_MS >= 4_000,
    "the extension owner outlives the host's two-second graceful and one-second terminate bounds");
  const artifactDir = path.resolve(path.dirname(fakeHost), "..", "..", "..", "out", "tests", "conversation-client");
  fs.mkdirSync(artifactDir, { recursive: true });
  for (const mode of ["cleanup", "malformed_cleanup"] as const) {
    const marker = path.join(artifactDir, `cleanup-${mode}-${process.pid}-${Date.now()}.txt`);
    const spec = fake(mode);
    spec.env.INTERACT_FAKE_CLEANUP_MARKER = marker;
    const client = createConversationClient(spec);
    try {
      await client.catalog();
      if (mode === "cleanup") client.dispose();
      else {
        const deadline = Date.now() + 1000;
        while (client.state() !== "crashed" && Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, 10));
        }
        assert.equal(client.state(), "crashed");
      }
      const deadline = Date.now() + 1000;
      while (!fs.existsSync(marker) && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 10));
      }
      assert.equal(fs.readFileSync(marker, "utf8"), "stdin closed", mode);
    } finally {
      client.dispose();
      if (fs.existsSync(marker)) fs.unlinkSync(marker);
    }
  }
});

test("provider errors cannot echo paths, prompts or credential-shaped text", async () => {
  // The host response is hostile even though it is local: provider stderr routinely carries
  // account and filesystem context, neither of which belongs in the panel or extension log.
  const visible: string[] = [];
  const client = createConversationClient(fake("adversarial_error"), {
    onError: (message) => visible.push(message),
  });
  try {
    let rejected = "";
    try {
      await client.catalog();
      assert.fail("the hostile provider response must fail initialization");
    } catch (error) {
      rejected = error instanceof Error ? error.message : String(error);
    }
    assert.match(rejected, /internal_error: The local conversation host failed/i);
    assert.equal(visible.length, 1, "the same generic failure must reach the visible host callback");
    const shown = `${visible.join(" ")} ${rejected}`;
    for (const secret of ["api_key", "secret-value", "/home/private", "private prompt"]) {
      assert.ok(!shown.includes(secret), `${secret} must stay behind the process boundary`);
    }
  } finally {
    client.dispose();
  }
});

test("incompatible, crashed and malformed hosts fail visibly without reconnecting", async () => {
  // These are distinct external-seam failures but share one invariant: the same client becomes
  // terminal and a second paid/ambiguous process is never started automatically.
  for (const mode of ["incompatible", "crash", "crash_on_start", "malformed"] as const) {
    const errors: string[] = [];
    const states: string[] = [];
    const client = createConversationClient(fake(mode), {
      onError: (message) => errors.push(message),
      onState: (state) => states.push(state),
    });
    try {
      if (mode === "incompatible") {
        await assert.rejects(client.catalog(), /does not support/i);
      } else if (mode === "crash_on_start") {
        await client.catalog();
        await assert.rejects(client.start({
          route_id: "session-route",
          prompt: "retain this exact prompt",
          selection: { model: "example-model" },
          workspace_root: path.dirname(fakeHost),
        }), /stopped|crash|protocol|closed/i);
        assert.equal(client.state(), "crashed", "the first dispatch must expose the bridge exit");
      } else {
        await client.catalog();
        await new Promise((resolve) => setTimeout(resolve, 30));
        assert.equal(client.state(), "crashed", `${mode} must make the one process terminal`);
        await assert.rejects(client.send("root-run", "do not retry"),
          /stopped|crash|protocol|malformed/i);
      }
      assert.ok(errors.length > 0, `${mode} must be visible to the host UI`);
      assert.notEqual(client.state(), "connecting");
      for (const state of new Set(states)) {
        assert.equal(states.filter((candidate) => candidate === state).length, 1,
          `${mode} must emit ${state} exactly once`);
      }
    } finally {
      client.dispose();
    }
  }
});
