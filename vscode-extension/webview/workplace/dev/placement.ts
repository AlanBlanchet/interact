/** WHERE PEOPLE STAND, checked against the building rather than against a screenshot.
 *
 *  "Sprites are very weirdly placed, and are just simply bad."
 *
 *  That defect had no visible symptom worth the name. Everybody was on the floor, nobody was in a
 *  wall, and every screenshot looked like a room with people in it — the placement was simply
 *  MEANINGLESS: two ranks that collapsed onto the same row in any depth-6 room, an overflow rule
 *  that pushed the extra bodies one row NORTH onto the desks they were supposed to be working at,
 *  and a "rest" rank standing three tiles from the nearest thing to sit on. None of it throws, so
 *  none of it shows up in a test that renders strings, and by the time it is visible in pixels it
 *  is one frame of a simulation that is always moving.
 *
 *  So the rule is stated as an invariant over the built world instead, and it is one line:
 *
 *      A PLACE IS DEFINED BY WHAT IS BEHIND IT.
 *
 *  Every standing place that claims something to sit on must have that something on the tile
 *  directly north of it — a desk for a working place, a couch or a bench for a resting one. A
 *  place that has nothing declares `perch: false` and its occupant is drawn standing. There is no
 *  third case, and a seat that cannot say which it is is the bug.
 *
 *  Prints one line per room and exits non-zero on any violation, so it can be run by hand or by
 *  the suite:
 *
 *      node out-placement.js
 */
import { brainOf, deptsOf, placeOf, seating, worldFor } from "../scene";
import { PITCH } from "../world";
import type { Cast } from "../scene";
import { fixture } from "./fixture";

/** What a body may actually sit at or on. Everything else behind a seat is scenery. */
const PERCHES = new Set(["desk", "drafting", "sofa", "bench", "chair"]);

interface Fault {
  room: string;
  seat: string;
  behind: string;
}

function main(): void {
  const cast = fixture().workers as Cast[];
  const world = worldFor(cast);
  const faults: Fault[] = [];
  let seats = 0;
  let perched = 0;

  for (const room of world.rooms) {
    const props = new Map(room.props.map((p) => [p.x + ":" + p.y, String(p.tile)]));
    const here: Fault[] = [];
    for (const seat of room.seats) {
      seats++;
      const key = (room.id || "(lobby)") + " " + (seat.post ?? "desk") + " (" + seat.x + "," + seat.y + ")";
      if (seat.perch === false) continue;
      perched++;
      const behind = props.get(seat.x + ":" + (seat.y - 1));
      if (!behind || !PERCHES.has(behind)) {
        here.push({ room: room.id || "(lobby)", seat: key, behind: behind ?? "nothing" });
      }
      // A place nobody can reach is a place nobody stands in. The cell itself must be walkable.
      if (world.solid[seat.y * world.cols + seat.x]) {
        here.push({ room: room.id || "(lobby)", seat: key, behind: "THE SEAT ITSELF IS SOLID" });
      }
    }
    faults.push(...here);
    const label = (room.id || "(lobby)").padEnd(12);
    console.log(`${label} seats=${String(room.seats.length).padStart(3)}  faults=${here.length}`);
  }

  /* ── AND NO TWO PLACES MAY CROWD EACH OTHER ────────────────────────────────────────────────
     The second half of the rule, and the half that came back after being fixed once. A nameplate
     is capped at 66 world pixels against a 24-pixel tile, so two people two tiles apart wear
     plates that overlap by eighteen; and a body's capability glyphs hang at its feet and run
     twenty-two pixels past them, through the face of anybody two rows in front.
     A room emits rows of seats from FOUR different places — the desk banks, the standing
     overflow, the lobby's waiting bench, the yard's path — and a fix applied to one of them left
     the other three collided, which an independent critic found in two rooms in both themes. So
     the rule is checked over every PAIR, and the code has one constant for it. */
  const crowded: string[] = [];
  for (const room of world.rooms) {
    for (let i = 0; i < room.seats.length; i++) {
      for (let j = i + 1; j < room.seats.length; j++) {
        const a = room.seats[i];
        const b = room.seats[j];
        if (Math.abs(a.x - b.x) >= PITCH || Math.abs(a.y - b.y) >= PITCH) continue;
        crowded.push(
          `${room.id || "(lobby)"}: (${a.x},${a.y}) and (${b.x},${b.y}) are ` +
            `${Math.abs(a.x - b.x)}x${Math.abs(a.y - b.y)} apart, under the ${PITCH}-tile pitch`,
        );
      }
    }
  }

  /* ── AND THE PLACES A REAL CAST IS ACTUALLY GIVEN ─────────────────────────────────────────
     Everything above checks what the BUILDING declares. What a body stands on is what `seating`
     HANDS it, and those were two different sets: the hand-out used to wrap an exhausted pool by
     stepping one tile off a real place, inventing a coordinate the building never agreed to and
     that no invariant over `room.seats` could ever see. Three finished agents in a two-couch room
     put the third one a single tile from the first — sprites overlapping, nameplates illegible —
     while every check here reported the room correct. So the hand-out is checked too. */
  const given = [...seating(world, cast, brainOf(cast)).entries()];
  const byRoom = new Map<string, [string, { x: number; y: number }][]>();
  for (const [id, seat] of given) {
    const home = placeOf(world, cast.find((w) => w.run_id === id)!).id || "(lobby)";
    byRoom.set(home, [...(byRoom.get(home) ?? []), [id, seat]]);
  }
  const collided: string[] = [];
  for (const [room, list] of byRoom) {
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const [ai, a] = list[i];
        const [bi, b] = list[j];
        if (Math.abs(a.x - b.x) >= PITCH || Math.abs(a.y - b.y) >= PITCH) continue;
        collided.push(
          `${room}: ${ai} at (${a.x},${a.y}) and ${bi} at (${b.x},${b.y}) — ` +
            `${Math.abs(a.x - b.x)}x${Math.abs(a.y - b.y)} apart`,
        );
      }
    }
  }

  /* ── AND PAST CAPACITY, WHERE NOTHING RANDOM WILL EVER TAKE YOU ───────────────────────────
     A room is built with three places per two people, so no real roster can exhaust one — which
     is precisely why the overflow path shipped with a bug that stacked EVERY body past the first
     onto one identical tile, and why no fixture, no screenshot and no live sweep could have found
     it. Driven deliberately here: one room, three times more finished agents than it has places,
     and every place handed out must still be distinct and a PITCH apart. */
  {
    const room = world.rooms.find((r) => r.seats.length >= 4 && !!r.id && !r.open);
    if (room) {
      const crowd: Cast[] = [];
      for (let i = 0; i < room.seats.length * 3; i++) {
        crowd.push({ ...cast[0], run_id: "flood" + i, status: "done", department: room.id, zone: "code" } as Cast);
      }
      const spots = [...seating(world, crowd, null).values()];
      const seen = new Map<string, number>();
      let stacked = 0;
      let tight = 0;
      for (const a of spots) {
        const key = a.x + ":" + a.y;
        seen.set(key, (seen.get(key) ?? 0) + 1);
        if ((seen.get(key) ?? 0) > 1) stacked++;
      }
      for (let i = 0; i < spots.length; i++) {
        for (let j = i + 1; j < spots.length; j++) {
          if (Math.abs(spots[i].x - spots[j].x) < PITCH && Math.abs(spots[i].y - spots[j].y) < PITCH) tight++;
        }
      }
      console.log(
        `\noverflow: ${spots.length} finished agents into ${room.id} (${room.seats.length} places) ` +
          `-> ${seen.size} distinct spots, ${stacked} stacked, ${tight} pairs under the pitch.`,
      );
      if (stacked || tight) {
        console.log("  OVERFLOW STACKS BODIES:", JSON.stringify(spots.map((a) => [a.x, a.y])));
        process.exitCode = 1;
      }
    }
  }

  console.log(`\n${seats} places, ${perched} of them claiming something to sit on.`);
  console.log(`${given.length} people placed, ${collided.length} of them crowding somebody.`);
  console.log(`${deptsOf(cast).length} departments.`);
  if (collided.length) {
    console.log("\nPEOPLE HANDED PLACES TOO CLOSE TOGETHER:");
    for (const c of collided) console.log("  " + c);
  }
  if (crowded.length) {
    console.log("\nPLACES TOO CLOSE TOGETHER:");
    for (const c of crowded) console.log("  " + c);
  }
  if (faults.length || crowded.length || collided.length) {
    if (faults.length) {
      console.log("\nPLACES WITH NOTHING BEHIND THEM:");
      for (const f of faults) console.log(`  ${f.seat} -> ${f.behind}`);
    }
    process.exit(1);
  }
  console.log(`Every place has the thing it belongs to behind it, and none is within ${PITCH} tiles of another.`);
}

main();
