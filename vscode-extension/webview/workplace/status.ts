/** ONE STATUS VOCABULARY, for the building and for the desk.
 *
 *  The two panels shared their sprites, their palette and their pod colours, and still said the
 *  same fact two different ways. The side bar's loudest device was a stamped word — ERROR, DONE,
 *  HELD, NOT OURS — pressed across a work order. The building said the identical states with a
 *  6px mark in a nameplate and a small blinking wedge, and put the WORDS in a legend at the very
 *  bottom of the view. So a person reading the map had to learn a second, much quieter code for
 *  the fact the side bar shouts, and the building had no text-badge vocabulary at all.
 *
 *  Two things had drifted, not one. The SHAPES said the same thing; the WORDS did not exist in the
 *  building, and where they did — in the board by the door — they were different words: "stuck"
 *  for what the desk calls ERROR, "finished" for DONE, "idle 2m+" for HELD. Two lexicons for one
 *  set of facts is the same defect as two allocators for one set of colours.
 *
 *  So the vocabulary lives here, once: which states are worth saying out loud, what each is
 *  CALLED, what SHAPE marks it, and what the stamp is made of. Both surfaces import it. Neither
 *  is allowed a second opinion.
 *
 *  What is deliberately NOT shared is where the stamp lands, because the two objects are genuinely
 *  different: on the desk a stamp is ink pressed into paper, so it is an outline with no shadow
 *  and nothing behind it; in the building it is a placard standing over someone's head, so it is
 *  opaque and throws the same hard pixel shadow every other sign in that building throws. Same
 *  word, same box, same tilt, same colours — mounted the way each place actually mounts things.
 */
import { draw } from "./pixels";
import { MARKS } from "./art";
import { STATUS, type Attention } from "../../src/statusLanguage";

/** Past two minutes of nothing, a worker is not working. Both surfaces used to declare this
 *  privately, which is precisely how two views end up disagreeing about who is stalled. */
export const STALL_SECONDS = 120;

/** The states worth saying out loud. WORKING is not one of them: an open job with nothing
 *  stamped on it is the oldest "in progress" signal there is, and leaving it unstamped is what
 *  keeps the loud marks meaning something.
 *
 *  These are `Attention` values, not a private enum. The building used to name its own four
 *  states (`done` / `error` / `held` / `foreign`) beside a rail that named six — same taxonomy,
 *  two spellings, which is how one product ends up looking like two.
 */
export type StampKind = Exclude<Attention, "working" | "ready">;

export interface Stamp {
  kind: StampKind;
  /** The word, as it is printed. Comes from `statusLanguage`, never from here. */
  word: string;
  /** Which mark in `MARKS` carries this state as a SHAPE. The rail's `mark` is a TEXT glyph and
   *  the fonts a webview actually has do not carry half of them (six identical tofu boxes was the
   *  last attempt) — so the world draws the same MEANING in its own pixels. Word and accent are
   *  shared; only the rendering of the shape is each surface's own. */
  mark: string;
  /** The theme variable this state is tinted with, on BOTH surfaces. */
  accent: string;
}

/** Which pixel drawing carries each state. `art.ts` owns the shapes; this is the only place that
 *  says which shape means which state. */
const SHAPES: Record<StampKind, string> = {
  error: "error",
  asked: "asked",
  held: "held",
  finished: "done",
  "not-ours": "foreign",
  /* A filled block: the tape-deck stop, the one mark that means "a person ended this". */
  stopped: "stopped",
};

function stampOf(kind: StampKind): Stamp {
  const voice = STATUS[kind];
  return { kind, word: voice.word, mark: SHAPES[kind], accent: voice.accent };
}

export const STAMPS: Record<StampKind, Stamp> = {
  error: stampOf("error"),
  asked: stampOf("asked"),
  held: stampOf("held"),
  finished: stampOf("finished"),
  "not-ours": stampOf("not-ours"),
  stopped: stampOf("stopped"),
};

/** What a counter calls each state. Lowercase here — a tally is prose, a stamp is a stamp — but
 *  it is the SAME word underneath, which is the whole point of the table. */
export const WORDS = {
  running: "on",
  done: STATUS.finished.word.toLowerCase(),
  error: STATUS.error.word.toLowerCase(),
  held: STATUS.held.word.toLowerCase(),
  foreign: STATUS["not-ours"].word.toLowerCase(),
} as const;

/** Anything either surface can hand this module. Neither view's row type is imported, so this
 *  file cannot drag a view model across the seam. */
export interface Standing {
  status: string;
  idle_seconds: number;
}

/** THE rule for what a run is showing, in one place — and it produces the RAIL's vocabulary,
 *  not a second one.
 *
 *  Note the order: a dead run is ERROR even if it has been dead for an hour, and only a RUNNING
 *  one can be HELD. Sleeping a finished or foreign run says "stuck" when it is simply over — the
 *  building used to do exactly that, snoozing a DONE worker, while the desk did not.
 *
 *  ASKED is deliberately unreachable from here and that is a DATA gap, not an omission: the rail
 *  gets `awaitingReply` from the run record, and the workplace's own view model never carried it.
 *  The state is declared so the world can draw it the day the field arrives.
 */
export function attentionOf(w: Standing): Attention {
  if (w.status === "error") return "error";
  if (w.status === "foreign") return "not-ours";
  /* Declared in the company, never asked. Reaches here only once the floor status carries it —
     `floorStatus` used to collapse declared into done, which conflated "waiting for a first job"
     with "did its job"; two different stories, and the posture system tells them apart. */
  if (w.status === "ready") return "ready";
  if (w.status === "done") return "finished";
  return w.idle_seconds >= STALL_SECONDS ? "held" : "working";
}

export function stampFor(w: Standing): Stamp | null {
  const a = attentionOf(w);
  // Working and ready carry no placard: one is busy, the other has simply not been asked yet.
  return a === "working" || a === "ready" ? null : STAMPS[a];
}

/* ── the state a BODY carries, rather than a placard ─────────────────────────────────────────
 *
 *  "All the agents say finished whereas we don't care... Instead they could have a seat or rest
 *  in their room."
 *
 *  The stamp is a good device and it was being spent on everything. Four of the five states worth
 *  saying got the same treatment as the one that wants somebody NOW, so a floor of finished work
 *  shouted exactly as loudly as a crash, and the loudest thing on screen was a word that means
 *  "nothing to do here".
 *
 *  So the ordinary states move into the BODY — where a person is in their room, and what they are
 *  doing there — and the placard is kept for the two that genuinely want a human being:
 *
 *      ERROR     standing, out of the chair, plate burning, room lit red.   STAMPED.
 *      ASKED     standing at the desk, turned toward the door.              STAMPED.
 *      WORKING   sitting at their own desk, elbows out, typing.             no stamp.
 *      HELD      the same seat, head down, eyes shut, z's.                  no stamp.
 *      FINISHED  walked to the rest end of their room and sat down.         no stamp.
 *      NOT OURS  never had a desk here: a visitor, sitting at the rest end. no stamp.
 *
 *  Nothing is deleted from the vocabulary — the rail still prints all six words, marks and
 *  accents, and `stampFor` above still answers for the six, because the side bar renders a LIST
 *  and a list has no posture to spend. This is the WORLD's reading of the same table.
 */
export type Posture = "sit" | "slump" | "lounge" | "stand";

export interface Behaviour {
  /** Which sprite pair the body rests in. */
  posture: Posture;
  /** Which end of its room it occupies. */
  post: "desk" | "rest";
  /** Whether the world hangs a placard over it. */
  stamp: boolean;
}

const BEHAVIOUR: Record<Attention, Behaviour> = {
  working: { posture: "sit", post: "desk", stamp: false },
  held: { posture: "slump", post: "desk", stamp: false },
  error: { posture: "stand", post: "desk", stamp: true },
  asked: { posture: "stand", post: "desk", stamp: true },
  finished: { posture: "sit", post: "rest", stamp: false },
  "not-ours": { posture: "sit", post: "rest", stamp: false },
  /* Declared in the company, never asked: STANDING AT ITS DESK — no placard, no caption, no
     rest fade. Posture ALONE was measured imperceptible beside the loungers, so the distinction
     is position AND posture together, in the same wordless language every other state speaks:
     a body that DID its work is ON the couch at the rest end; a body still waiting for its
     first job stands at its station. Thirty declared-but-idle agents at their desks reading as
     a staffed floor waiting for work is the honest picture of a big roster. */
  ready: { posture: "stand", post: "desk", stamp: false },
  /* Killed by a person: stands at its desk wearing the word — not success, not an alarm. */
  stopped: { posture: "stand", post: "desk", stamp: true },
};

export function behaviourOf(a: Attention): Behaviour {
  return BEHAVIOUR[a] ?? BEHAVIOUR.working;
}

/** How tall a body in each posture is ON SCREEN, in device pixels: the grid's rows plus the
 *  derived rim, times the sprite scale.
 *
 *  Stated ONCE because four different things have to agree with it to the pixel — the nameplate
 *  and the placard, which hang off the head; the speech layout's reserved rectangles, which are
 *  what promise that no two labels are drawn over each other; and the stylesheet. They were four
 *  hand-tuned constants tuned for one sprite height, and a posture that changes the height by
 *  twelve pixels silently invalidates all of them at once: a name floating a finger's width above
 *  somebody's head, and a reserve box that refuses bubbles over empty air while allowing one over
 *  a word. */
export const HEAD: Record<Posture, number> = {
  /* A Kenney doll is a 16px frame drawn at 2x: 32 on screen, boots on the anchor. */
  stand: 32,
  /* Seated tucks the figure four pixels toward its desk. */
  sit: 28,
  slump: 28,
  /* Rotated onto the couch — the figure lies, so its top is the doll's WIDTH. */
  lounge: 22,
};

/** The stamp the WORLD hangs, which is not the stamp the rail prints. Two states earn a placard
 *  over somebody's head; the rest are said by what the body is doing. */
export function worldStampFor(w: Standing): Stamp | null {
  const a = attentionOf(w);
  return behaviourOf(a).stamp ? STAMPS[a as StampKind] : null;
}

/** Only work can stall. Used by both surfaces for the sleep mark and the stopped ambient. */
export function isHeld(w: Standing): boolean {
  return w.status === "running" && w.idle_seconds >= STALL_SECONDS;
}

/** The mark for a state, drawn through the workplace's own pixel engine — the same rectangles in
 *  both views, not a lookalike. */
export function markOf(status: string, scale = 2): string {
  const piece = MARKS[status] ?? MARKS.foreign;
  return draw(piece.grid, piece.pal, { scale, outline: false });
}

/** The stamp itself. One element, one class, both panels. */
export function stampHtml(s: Stamp, scale = 2): string {
  return (
    `<span class="wp-stamp" data-kind="${s.kind}" style="--voice:var(${s.accent})">` +
    `${markOf(s.mark, scale)}<b>${s.word}</b></span>`
  );
}

/** The stamp, as CSS, embedded verbatim by both stylesheets.
 *
 *  Everything that makes the device recognisable is fixed here — the 2px rule, the tilt, the
 *  uppercase tracking, the weight, and the four colour treatments. What each panel supplies is
 *  only how the thing is MOUNTED on its own substrate, through four custom properties:
 *
 *    --stamp-ink     the substrate's own near-black, mixed into every outline colour
 *    --stamp-quiet   the substrate's dim text colour, the default when a kind sets nothing
 *    --stamp-mix     how much of the status hue survives that mix, per theme
 *    --stamp-bg      what is behind the letters (paper: nothing; a room: the panel colour)
 *    --stamp-shadow  a placard casts one; ink pressed into paper does not
 *
 *  ERROR is the one kind that is fully specified here and takes no substrate knob at all. Red on
 *  either stock cannot reach the text floor while still reading as red — measured 3.3-3.6:1 in
 *  dark by two independent methods — so it stops being an outline and becomes a filled plate,
 *  mixed DOWN toward a near-black red so that one pairing (white on it) holds in both themes.
 */
export const STAMP_CSS = String.raw`
.wp-stamp {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 4px 2px;
  border: 2px solid currentColor;
  color: var(--stamp, var(--stamp-quiet, currentColor));
  background: var(--stamp-bg, transparent);
  box-shadow: var(--stamp-shadow, 0 0 0 0 transparent);
  --mark: currentColor;
  /* 10px, not 9: a rotated 2px outline is mostly anti-aliased edge, so the stamp measured weaker
     than the text it sits beside even at the same colour. */
  font-size: var(--stamp-size, 10px);
  font-weight: 700;
  line-height: 1;
  letter-spacing: .11em;
  white-space: nowrap;
  text-transform: uppercase;
  transform: rotate(-7deg);
}
.wp-stamp svg { display: block; }
.wp-stamp[data-kind="finished"], .wp-stamp[data-kind="asked"] {
  --stamp: color-mix(in srgb, var(--voice) var(--stamp-mix, 52%), var(--stamp-ink));
}
.wp-stamp[data-kind="not-ours"], .wp-stamp[data-kind="held"] { --stamp: var(--stamp-ink); }
.wp-stamp[data-kind="error"] {
  --stamp: #fff;
  background: color-mix(in srgb, var(--voice) 58%, #1a0508);
  border-color: color-mix(in srgb, var(--voice) 58%, #1a0508);
  /* The one state where a person is wanted NOW keeps a piece of motion, and it is a halo rather
     than a blink: blinking a word to 15% opacity makes it unreadable half the time, which is a
     strange thing to do to the only word that matters. The plate holds still and full strength;
     the alarm ring is what moves. On the beat, like everything else here. */
  animation: wp-stamp-alarm calc(var(--beat) * 2 / 3) ease-in-out infinite;
}
@keyframes wp-stamp-alarm {
  0%, 100% { box-shadow: var(--stamp-shadow, 0 0 0 0 transparent), 0 0 0 0 color-mix(in srgb, var(--voice) 65%, transparent); }
  50% { box-shadow: var(--stamp-shadow, 0 0 0 0 transparent), 0 0 0 5px color-mix(in srgb, var(--voice) 0%, transparent); }
}
@media (prefers-reduced-motion: reduce) {
  .wp-stamp[data-kind="error"] { animation: none; }
}
`;
