/** Your OWN sessions, readable — the provider-transcript half of the conversation view.
 *
 *  A foreign run's id IS its Claude session id, and Claude Code files every session under
 *  `~/.claude/projects/<cwd with "/" and "." as "-">/<session-id>.jsonl`. Mapping that shape
 *  into ours is what turns a "your session" row from a grey dead thing into a place — the
 *  panel can SHOW the session, which is the half of "chat just like in claude code" a session
 *  interact did not start can honestly have (watching, not steering: it is already being
 *  steered, by you, in its window).
 *
 *  Runtime-import-free apart from node builtins, so `node --test` can load it directly — the
 *  same discipline as `rail.ts` (the loader demands ".ts" specifiers tsc refuses to emit).
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { AgentActivity, AgentRun } from "./agents";

/** Where the provider files one of your sessions. */
export function foreignTranscriptPath(
  run: Pick<AgentRun, "run_id" | "cwd">,
  home: string = os.homedir(),
): string | null {
  if (!run.cwd) return null;
  return path.join(home, ".claude", "projects", run.cwd.replace(/[/.]/g, "-"), `${run.run_id}.jsonl`);
}

/** The TAIL of a file. These transcripts grow to hundreds of MB, so reading the whole file per
 *  refresh would make the panel scale with the longest session on the machine; the last chunk
 *  is read and the first partial line dropped. */
function tailText(file: string, bytes: number): string | null {
  let fd: number;
  try {
    fd = fs.openSync(file, "r");
  } catch {
    return null;
  }
  try {
    const size = fs.fstatSync(fd).size;
    const start = Math.max(0, size - bytes);
    const buf = Buffer.alloc(size - start);
    fs.readSync(fd, buf, 0, buf.length, start);
    const text = buf.toString("utf8");
    return start === 0 ? text : text.slice(text.indexOf("\n") + 1);
  } catch {
    return null;
  } finally {
    fs.closeSync(fd);
  }
}

/** One of your own sessions' recent activity, mapped from the provider's transcript shape to
 *  ours — so the conversation view renders it with the exact grammar every other transcript
 *  gets. Only the shapes worth reading map; housekeeping lines are skipped. */
export function readForeignActivity(
  run: Pick<AgentRun, "run_id" | "cwd">,
  limit = 40,
  home?: string,
): AgentActivity[] {
  const file = foreignTranscriptPath(run, home);
  if (!file) return [];
  const text = tailText(file, limit > 100 ? 1 << 20 : 1 << 18);
  if (!text) return [];
  const out: AgentActivity[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let raw: unknown;
    try {
      raw = JSON.parse(line);
    } catch {
      continue;
    }
    const t = raw as { type?: string; timestamp?: string;
      message?: { content?: unknown } };
    const at = t.timestamp ? Date.parse(t.timestamp) / 1000 : null;
    const stamp = Number.isFinite(at) ? at : null;
    if (t.type === "assistant" && Array.isArray(t.message?.content)) {
      for (const block of t.message.content as Array<Record<string, unknown>>) {
        if (block.type === "text" && String(block.text ?? "").trim()) {
          out.push({ kind: "text", text: String(block.text), at: stamp });
        } else if (block.type === "thinking" && String(block.thinking ?? "").trim()) {
          out.push({ kind: "thinking", text: String(block.thinking), at: stamp });
        } else if (block.type === "tool_use") {
          out.push({ kind: "tool", text: "", tool: String(block.name ?? ""),
                     tool_input: JSON.stringify(block.input ?? {}).slice(0, 400), at: stamp });
        }
      }
    } else if (t.type === "user") {
      const content = t.message?.content;
      if (typeof content === "string") {
        if (content.trim()) out.push({ kind: "prompt", text: content, at: stamp });
      } else if (Array.isArray(content)) {
        for (const block of content as Array<Record<string, unknown>>) {
          if (block.type === "text" && String(block.text ?? "").trim()) {
            out.push({ kind: "prompt", text: String(block.text), at: stamp });
          } else if (block.type === "tool_result") {
            const inner = block.content;
            const said = typeof inner === "string"
              ? inner
              : Array.isArray(inner)
                ? (inner as Array<Record<string, unknown>>)
                    .filter((b) => b.type === "text").map((b) => String(b.text ?? "")).join("\n")
                : "";
            out.push({ kind: "tool_result", text: said.slice(0, 4000), at: stamp });
          }
        }
      }
    }
  }
  return out.slice(-Math.max(1, limit));
}
