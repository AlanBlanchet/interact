/** A capability nobody can reach is not a capability.
 *
 *  Three times in one arc a feature was written, tested, and left unwired — the workspace scope
 *  most recently, which existed as two well-tested modules bound to no command and therefore
 *  invisible to the person who asked for it. A unit test on the logic passes happily in that
 *  state, which is exactly why it needs its own check: every command the extension registers must
 *  be declared in the manifest, and every command the manifest declares must be registered.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(readFileSync(join(here, "..", "package.json"), "utf8"));
const source = readFileSync(join(here, "extension.ts"), "utf8");
const require = createRequire(import.meta.url);

const declared: string[] = (manifest.contributes.commands ?? []).map((c: { command: string }) => c.command);
const registered = [...source.matchAll(/registerCommand\(\s*"([^"]+)"/g)].map((m) => m[1]);

test("every command the manifest advertises is actually implemented", () => {
  const missing = declared.filter((c) => !registered.includes(c));
  assert.deepEqual(missing, [], "advertised in the command palette, does nothing when invoked");
});

/** Commands invoked only in code, never by a person.
 *
 *  Each takes an argument that a palette entry could not supply — `interact.agents.chat` needs a
 *  run id — so declaring them would put a broken row in the command palette. Listed explicitly so
 *  that "internal" is a decision someone made, not a manifest entry someone forgot.
 */
const INTERNAL = ["interact.agents.chat"];

test("every command the extension implements is reachable, or explicitly internal", () => {
  const hidden = registered.filter((c) => !declared.includes(c) && !INTERNAL.includes(c));
  assert.deepEqual(hidden, [], "implemented but unreachable — nobody can invoke it");
});

test("the internal list does not hide something that IS declared", () => {
  // Otherwise the exemption quietly grows into a place to park things.
  assert.deepEqual(INTERNAL.filter((c) => declared.includes(c)), []);
});

test("the workspace switcher is reachable from the panel's title bar", () => {
  // The specific one he could not reach: "i can't change the workspace... i have agents in the
  // 'sheets' folder elsewhere, and i can't change and see how they work."
  const menus = manifest.contributes.menus["view/title"] ?? [];
  const entry = menus.find((m: { command: string }) => m.command === "interact.agents.workspace");
  assert.ok(entry, "no title-bar button, so the only way in is the command palette");
  assert.match(entry.when, /interactAgents\.board/);
});

test("every slash command in the chat invokes a command that exists", () => {
  // The chat menu is a second place a capability can be advertised and wired to nothing.
  const { CHAT_COMMANDS } = require("../out/chatCommands.js");
  const missing = CHAT_COMMANDS
    .map((c: { slash: string; command: string }) => c)
    .filter((c: { command: string }) => !registered.includes(c.command))
    .map((c: { slash: string; command: string }) => `${c.slash} -> ${c.command}`);
  assert.deepEqual(missing, [], "advertised in the chat menu, invokes nothing");
});
