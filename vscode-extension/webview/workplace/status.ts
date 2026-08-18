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

/** Past two minutes of nothing, a worker is not working. Both surfaces used to declare this
 *  privately, which is precisely how two views end up disagreeing about who is stalled. */
export const STALL_SECONDS = 120;

/** The states worth saying out loud. RUNNING is not one of them: an open job with nothing stamped
 *  on it is the oldest "in progress" signal there is, and leaving it unstamped is what keeps the
 *  loud marks meaning something. */
export type StampKind = "done" | "error" | "held" | "foreign";

export interface Stamp {
  kind: StampKind;
  /** The word, as it is printed. Uppercase is the stamp's, not the data's. */
  word: string;
  /** Which mark in `MARKS` carries this state as a SHAPE. */
  mark: string;
}

export const STAMPS: Record<StampKind, Stamp> = {
  done: { kind: "done", word: "DONE", mark: "done" },
  error: { kind: "error", word: "ERROR", mark: "error" },
  held: { kind: "held", word: "HELD", mark: "held" },
  foreign: { kind: "foreign", word: "NOT OURS", mark: "foreign" },
};

/** What a counter calls each state. Lowercase here — a tally is prose, a stamp is a stamp — but
 *  it is the SAME word underneath, which is the whole point of the table. */
export const WORDS = {
  running: "on",
  done: "done",
  error: "error",
  held: "held",
  foreign: "not ours",
} as const;

/** Anything either surface can hand this module. Neither view's row type is imported, so this
 *  file cannot drag a view model across the seam. */
export interface Standing {
  status: string;
  idle_seconds: number;
}

/** THE rule for what a run is showing, in one place.
 *
 *  Note the order: a dead run is ERROR even if it has been dead for an hour, and only a RUNNING
 *  one can be HELD. Sleeping a finished or foreign run says "stuck" when it is simply over — the
 *  building used to do exactly that, snoozing a DONE worker, while the desk did not.
 */
export function stampFor(w: Standing): Stamp | null {
  if (w.status === "error") return STAMPS.error;
  if (w.status === "done") return STAMPS.done;
  if (w.status === "foreign") return STAMPS.foreign;
  if (w.status === "running" && w.idle_seconds >= STALL_SECONDS) return STAMPS.held;
  return null;
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
    `<span class="wp-stamp" data-kind="${s.kind}">` +
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
.wp-stamp[data-kind="done"] {
  --stamp: color-mix(in srgb, var(--wp-ok) var(--stamp-mix, 52%), var(--stamp-ink));
}
.wp-stamp[data-kind="foreign"], .wp-stamp[data-kind="held"] { --stamp: var(--stamp-ink); }
.wp-stamp[data-kind="error"] {
  --stamp: #fff;
  background: color-mix(in srgb, var(--wp-bad) 58%, #1a0508);
  border-color: color-mix(in srgb, var(--wp-bad) 58%, #1a0508);
  /* The one state where a person is wanted NOW keeps a piece of motion, and it is a halo rather
     than a blink: blinking a word to 15% opacity makes it unreadable half the time, which is a
     strange thing to do to the only word that matters. The plate holds still and full strength;
     the alarm ring is what moves. On the beat, like everything else here. */
  animation: wp-stamp-alarm calc(var(--beat) * 2 / 3) ease-in-out infinite;
}
@keyframes wp-stamp-alarm {
  0%, 100% { box-shadow: var(--stamp-shadow, 0 0 0 0 transparent), 0 0 0 0 color-mix(in srgb, var(--wp-bad) 65%, transparent); }
  50% { box-shadow: var(--stamp-shadow, 0 0 0 0 transparent), 0 0 0 5px color-mix(in srgb, var(--wp-bad) 0%, transparent); }
}
@media (prefers-reduced-motion: reduce) {
  .wp-stamp[data-kind="error"] { animation: none; }
}
`;
