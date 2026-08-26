/** Your own sessions, readable.
 *
 *  A foreign run's id is its Claude session id, and the provider files the transcript under a
 *  munged-cwd directory. Mapping that shape into ours is what turns a "your session" row from a
 *  grey dead thing into a place the panel can actually show.
 */
import { strict as assert } from "node:assert";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { foreignTranscriptPath, readForeignActivity } from "./foreignSession.ts";

test("the transcript path is the provider's munged-cwd convention", () => {
  const p = foreignTranscriptPath({ run_id: "sid-1", cwd: "/home/alan/dev/my.app" }, "/HOME");
  assert.equal(p, "/HOME/.claude/projects/-home-alan-dev-my-app/sid-1.jsonl");
  assert.equal(foreignTranscriptPath({ run_id: "x", cwd: "" }), null,
    "no working directory, no place to look");
});

test("a session's tail maps into the conversation grammar", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "foreign-"));
  const dir = path.join(home, ".claude", "projects", "-tmp-proj");
  fs.mkdirSync(dir, { recursive: true });
  const lines = [
    { type: "user", timestamp: "2026-08-26T10:00:00Z",
      message: { role: "user", content: "fix the panel" } },
    { type: "assistant", timestamp: "2026-08-26T10:00:05Z",
      message: { role: "assistant", content: [
        { type: "thinking", thinking: "the rail is the object" },
        { type: "text", text: "On it." },
        { type: "tool_use", name: "Bash", input: { command: "ls" } },
      ] } },
    { type: "user", timestamp: "2026-08-26T10:00:09Z",
      message: { role: "user", content: [
        { type: "tool_result", content: [{ type: "text", text: "a.ts\nb.ts" }] },
      ] } },
    { type: "progress" }, // housekeeping shapes are skipped, never crashed on
  ];
  fs.writeFileSync(path.join(dir, "sess.jsonl"),
    lines.map((l) => JSON.stringify(l)).join("\n") + "\n");
  const turns = readForeignActivity({ run_id: "sess", cwd: "/tmp/proj" }, 40, home);
  assert.deepEqual(turns.map((t) => t.kind), ["prompt", "thinking", "text", "tool", "tool_result"]);
  assert.equal(turns[0].text, "fix the panel");
  assert.equal(turns[3].tool, "Bash");
  assert.match(turns[3].tool_input ?? "", /"command":"ls"/);
  assert.equal(turns[4].text, "a.ts\nb.ts");
  assert.ok((turns[0].at ?? 0) > 1_700_000_000, "the provider's timestamp becomes our clock");
});

test("a missing transcript is an empty conversation, never a crash", () => {
  assert.deepEqual(readForeignActivity({ run_id: "ghost", cwd: "/nowhere" }, 40, "/no-such-home"), []);
});
