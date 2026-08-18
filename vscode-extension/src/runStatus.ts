/** Whether a run is really still going.
 *
 *  Liveness is the one field a record cannot vouch for: a crash leaves "running" behind with
 *  nothing to correct it, and a row that spins forever is worse than no row.
 *
 *  But the probe alone is not enough. `interact agents spawn` returns as soon as the agent is
 *  alive, so nobody is left waiting to write its exit code — the record still says "running" long
 *  after the process is gone. Reading that as a crash made every detached agent flash a warning
 *  icon at the very moment it succeeded. The agent's OWN stream settles it: a stream that reached
 *  its end is a run that finished, whoever failed to record the fact.
 */
export type RunStatus = "running" | "done" | "failed" | "crashed" | "stopped" | "foreign";

export function livenessOf(
  recorded: RunStatus,
  pid: number | null | undefined,
  processAlive: boolean,
  streamEnded: boolean,
): RunStatus {
  if (recorded !== "running") return recorded; // already settled; never second-guessed
  if (typeof pid !== "number") return recorded; // nothing to probe — a crash would be invented
  if (processAlive) return recorded;
  return streamEnded ? "done" : "crashed";
}
