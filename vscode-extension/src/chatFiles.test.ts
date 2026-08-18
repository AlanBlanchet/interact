import { strict as assert } from "node:assert";
import { test } from "node:test";

import { chatFiles } from "./chatFiles.ts";
import type { AgentRun } from "./agents.ts";

const RUN = { run_id: "r1", provider: "claude", name: "g", status: "done" } as AgentRun;
const all = () => true;

test("the system prompt comes from what the provider actually resolved", () => {
  // The extension used to rebuild `~/.claude/agents/<agent>.md` itself. That is one vendor's
  // layout hard-coded into a panel that is supposed to show runs from several — a Codex agent
  // would get a link to a Claude path that does not exist, so no link at all.
  const files = chatFiles(
    { ...RUN, agent: "researcher", definition_path: "/opt/codex/defs/researcher.toml" },
    "/runs", "/home/alan", all,
  );
  assert.equal(files.find((f) => f.label === "system prompt")?.path, "/opt/codex/defs/researcher.toml");
});

test("a run recorded before the path was tracked still gets its link", () => {
  const files = chatFiles({ ...RUN, agent: "researcher" }, "/runs", "/home/alan", all);
  assert.equal(
    files.find((f) => f.label === "system prompt")?.path,
    "/home/alan/.claude/agents/researcher.md",
  );
});

test("a plain run offers no system prompt", () => {
  const files = chatFiles(RUN, "/runs", "/home/alan", all);
  assert.equal(files.find((f) => f.label === "system prompt"), undefined);
});

test("its own artefacts are offered beside it", () => {
  const labels = chatFiles(RUN, "/runs", "/home/alan", all).map((f) => f.label);
  assert.deepEqual(labels, ["transcript", "raw stream", "messages"]);
});

test("a file that is not there is not offered — a button that opens nothing is worse", () => {
  const files = chatFiles(RUN, "/runs", "/home/alan", (p) => p.endsWith(".jsonl") && !p.includes("raw"));
  assert.deepEqual(files.map((f) => f.label), ["transcript", "messages"]);
});
