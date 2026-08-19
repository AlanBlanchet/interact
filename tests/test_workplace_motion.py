"""The workplace view's SIMULATION, exercised in a real browser.

The scene is plain JS embedded in the extension's webview, so nothing in the TypeScript unit
suite can reach it: those tests build strings, and every defect here lives in what the browser
RESOLVES from them. A still frame hides the whole class — the walker bug below rendered perfectly
in every screenshot of a standing team, and only appeared for the four seconds somebody walked.

The harness is the extension's own preview build (the same document, CSP and theme variables the
panel ships), so a pass here is a pass on what the panel renders.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parent.parent / "vscode-extension"
PREVIEW = EXT / "webview" / "workplace" / "dev" / "preview.ts"

#: NOT a list. The colours that make a sprite a person are read off the standing worker itself, so
#: this cannot drift from what the stylesheet declares. A hand-kept copy here disagreed with the
#: sim's own list — four of the six properties the fix copies were never checked, and the two that
#: were are carried by pre-existing code rather than by the fix. Adding a seventh colour to
#: `.wp-worker` now extends this test for free instead of silently escaping it.
COLOUR_PROPS_JS = """(el) => {
  const out = {};
  const style = getComputedStyle(el);
  for (let i = 0; i < style.length; i++) {
    const p = style[i];
    if (p.startsWith('--c-')) out[p] = style.getPropertyValue(p).trim();
  }
  return out;
}"""


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    """The real preview pages, built from source."""
    if not PREVIEW.exists() or shutil.which("npx") is None:
        pytest.skip("the extension's webview toolchain is not available here")
    out = tmp_path_factory.mktemp("workplace")
    bundle = out / "preview.js"
    build = subprocess.run(
        ["npx", "esbuild", str(PREVIEW), "--bundle", f"--outfile={bundle}",
         "--format=cjs", "--platform=node", "--target=es2022"],
        cwd=EXT, capture_output=True, text=True,
    )
    if build.returncode != 0:
        pytest.fail(f"the webview would not build:\n{build.stderr}")
    subprocess.run(["node", str(bundle), str(out)], check=True, capture_output=True)
    return out


@pytest.fixture(scope="module")
def page(scene):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        # Explicitly NOT reduced motion: every animation in this file is the thing under test, and
        # a harness that quietly disables them reports "identical" no matter what broke.
        pg = browser.new_page(viewport={"width": 1100, "height": 800},
                              reduced_motion="no-preference")
        pg.goto((scene / "live.html").as_uri())
        pg.wait_for_timeout(600)
        yield pg
        browser.close()


def _send_someone(page, *, depth: str | None = None) -> dict:
    """Put a real worker on a real journey and read every colour they wear, before and during.

    On demand rather than waiting for the sim's own schedule: the defect exists only WHILE a
    person walks, and racing a spontaneous trip is how it stayed invisible for so long.

    ``depth`` picks who travels — "0" for a lead, anything else for a report. Without it the first
    body in the fixture was taken, so the report test skipped whenever that happened to be a lead
    and was green forever.
    """
    return page.evaluate(
        """([readColours, wantDepth]) => {
          const colours = eval('(' + readColours + ')');
          const bodies = window.__wp && window.__wp.bodies;
          if (!bodies || !window.__wp.send) return {error: 'the sim exposes no bodies to drive'};
          for (const id in bodies) {
            const el = bodies[id].el;
            if (!el || !el.closest('.wp-pod')) continue;
            const d = el.getAttribute('data-depth');
            if (wantDepth === '0' && d !== '0') continue;
            if (wantDepth === 'report' && (d === '0' || d === null)) continue;
            const before = colours(el);
            const travel = window.__wp.send(id, bodies[id].zone === 'code' ? 'lab' : 'code');
            if (!travel || !travel.walker) continue;
            return {id, depth: d, before, after: colours(travel.walker)};
          }
          return {error: 'no matching body could be sent anywhere'};
        }""",
        [COLOUR_PROPS_JS, depth],
    )


def test_a_traveller_is_the_same_person_walking(page):
    """The defect: a walker is reparented onto the traffic layer, OUTSIDE its pod — and the shirt
    is resolved from `--accent`, which the pod supplies by inheritance. So a traveller left the
    room and instantly wore whatever accent was in scope on the traffic layer: not a missing
    colour but ANOTHER TEAM'S, in a view whose whole job is showing whose journey you watch.
    """
    moved = _send_someone(page)
    assert "error" not in moved, moved.get("error")

    wrong = {k: (v, moved["after"].get(k))
             for k, v in moved["before"].items() if moved["after"].get(k) != v}
    assert not wrong, (
        f"{moved['id']} changes colour the moment they start walking: "
        + "; ".join(f"{k} {was!r} -> {now!r}" for k, (was, now) in wrong.items())
    )


def test_the_shirt_a_traveller_wears_is_actually_painted(page):
    """Distinct from the test above, which only demands the two AGREE. Both being empty would
    satisfy it, and an unpainted sprite is the exact way this failed."""
    moved = _send_someone(page)
    assert "error" not in moved, moved.get("error")
    assert moved["after"]["--c-shirt"], "the walker's shirt resolves to nothing at all"


def test_a_report_keeps_its_lighter_tint_on_the_road(page):
    """A report is drawn in a LIGHTER mix of its lead's colour, so depth is visible at a glance.
    Rebuilding a walker's shirt from the pod's raw accent would repaint every report as its lead
    the moment it stepped into the corridor — correct-looking, and wrong.

    A report is DEMANDED rather than hoped for: the earlier version took whichever body came
    first and skipped when that was a lead, which made it green whether or not it ever ran. And
    the comparison is against the lead's own colour rather than a "60%" literal copied out of the
    stylesheet — the point is that the two DIFFER, not what the mix happens to be.
    """
    report = _send_someone(page, depth="report")
    assert "error" not in report, (
        f"{report.get('error')} — the fixture must contain a report for this to mean anything")
    lead = _send_someone(page, depth="0")
    assert "error" not in lead, lead.get("error")
    assert report["after"]["--c-shirt"] != lead["after"]["--c-shirt"], (
        "a report on the road wears its lead's colour exactly — depth is invisible mid-journey")


def test_two_notes_between_the_SAME_pair_do_not_stack(page):
    """The courier collision that IS reachable, and the two tests before this one could not see.

    Different pairs never stacked — `startErrand` routes foot-to-foot between two people, who
    never stand in the same place, so those paths differ at both endpoints whatever the lane says.
    Both earlier attempts therefore passed with the fix reverted, which is a test proving nothing.

    The real case is the SAME pair twice: a back-and-forth between two agents puts two A->B notes
    on the road at once, and identical endpoints meant an identical route. Keyed on the pair, they
    also got an identical lane and pace — perfectly stacked.
    """
    spread = page.evaluate(
        """() => {
          const bodies = window.__wp && window.__wp.bodies;
          if (!bodies || !window.__wp.note) return {error: 'the sim exposes no courier seam'};
          window.__wp.tick.on = false;
          // The scene's own notes hold both MAX_ERRANDS slots, so without this the couriers below
          // are queued and never dispatched — and the test measures the fixture's traffic instead
          // of its own. That is precisely how two earlier versions passed against a reverted fix.
          window.__wp.clearNotes();
          const ids = Object.keys(bodies);
          if (ids.length < 2) return {error: 'need two people to send a note between'};
          // The same two people, twice — a conversation, not two unrelated messages.
          window.__wp.note(ids[0], ids[1], 'first');
          window.__wp.note(ids[0], ids[1], 'second');
          window.__wp.step(performance.now() + 600);
          const seen = new Set();
          let runners = 0;
          for (const el of document.querySelectorAll('.wp-errand')) {
            const r = el.getBoundingClientRect();
            if (!r.width) continue;
            runners++;
            seen.add(Math.round(r.left) + ',' + Math.round(r.top));
          }
          return {runners, distinct: seen.size};
        }"""
    )
    assert "error" not in spread, spread.get("error")
    if spread["runners"] < 2:
        pytest.skip(f"only {spread['runners']} courier(s) on the road — nothing to collide")
    assert spread["distinct"] == spread["runners"], (
        f"{spread['runners']} couriers between the same two people occupy "
        f"{spread['distinct']} position(s) — stacked, so a conversation looks like one note")


# --- The chat panel's reliability, in a real browser -----------------------------------------
#
# "I want to be able to chat just like in claude code in vscode. And i still have none of that
# that is actually reliable." Two failures that destroy typed text, both invisible to any test
# that only builds strings:
#   - a failed send used to clear the box before the send was confirmed;
#   - a streaming update must not rebuild the document under someone who is mid-sentence.


@pytest.fixture(scope="module")
def chat_page(scene):
    """The chat document, rendered from source with the host's API stubbed."""
    playwright = pytest.importorskip("playwright.sync_api")
    render = Path("/tmp/chatrender.ts")
    if not render.exists():
        pytest.skip("the chat render fixture is not present")
    subprocess.run(["node", "--experimental-strip-types", str(render)],
                   check=True, capture_output=True)
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 420, "height": 600})
        pg.goto("file:///tmp/chat/dark.html")
        pg.wait_for_timeout(300)
        yield pg
        browser.close()


def test_a_failed_send_returns_your_message(chat_page):
    """It used to clear the box on submit, so a send to an agent that had ended left you a toast
    and nothing else. Losing typed text is the one thing a chat box must never do."""
    got = chat_page.evaluate(
        """() => {
          const box = document.getElementById('message');
          box.value = 'a message I do not want to lose';
          document.getElementById('composer').dispatchEvent(
            new Event('submit', {cancelable: true}));
          const emptied = box.value;
          window.dispatchEvent(new MessageEvent('message', {data: {type: 'sent', ok: false}}));
          return {emptied, restored: box.value};
        }"""
    )
    assert got["emptied"] == "", "the box must empty instantly — a laggy chat feels broken"
    assert got["restored"] == "a message I do not want to lose"


def test_a_streaming_update_does_not_wipe_what_you_are_typing(chat_page):
    """The panel patches the transcript while an agent works. Rebuilding the document instead
    would destroy a half-written reply every time the agent said anything."""
    got = chat_page.evaluate(
        """() => {
          const box = document.getElementById('message');
          box.value = 'half-typed thought';
          window.dispatchEvent(new MessageEvent('message',
            {data: {type: 'transcript', html: '<p>new turn</p>'}}));
          return box.value;
        }"""
    )
    assert got == "half-typed thought"


# --- The world's text stays readable, measured on what actually paints ------------------------
#
# A CSS-parsing guard for this already existed and stopped protecting anything the moment the
# tile rewrite renamed the element it watched: it now ERRORS with "no rule '.wp-plate {'" rather
# than failing, and a real light-theme regression walked straight through the gap — character
# names at 1.9:1 against a 4.5:1 floor.
#
# So this measures the RENDERED result instead. It cannot be dodged by a rename, it sees through
# color-mix() and inherited backgrounds that a text parse cannot resolve, and it fails rather than
# errors when a selector disappears.

#: WCAG AA for body text; large text (>=18px, or >=14px bold) may sit at 3.0.
AA_SMALL = 4.5
AA_LARGE = 3.0

_CONTRAST_JS = """() => {
  const px = (c) => {
    const cv = document.createElement('canvas'); cv.width = cv.height = 1;
    const x = cv.getContext('2d'); x.fillStyle = c; x.fillRect(0, 0, 1, 1);
    return [...x.getImageData(0, 0, 1, 1).data].slice(0, 3);
  };
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('[class^="wp-"], [class*=" wp-"]')) {
    if (!el.textContent || !el.textContent.trim()) continue;
    if (el.children.length) continue;                 // only leaves actually paint text
    const cls = el.className.toString().trim().split(/\\s+/)[0];
    if (!cls || seen.has(cls)) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || Number(s.opacity) === 0) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    seen.add(cls);
    // Walk up for the first non-transparent backdrop — the colour the text is really read on.
    let node = el, bg = 'rgba(0, 0, 0, 0)';
    while (node && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) {
      bg = getComputedStyle(node).backgroundColor; node = node.parentElement;
    }
    out.push({cls, size: parseFloat(s.fontSize), weight: s.fontWeight,
              fg: px(s.color), bg: px(bg)});
  }
  return out;
}"""


def _ratio(fg, bg) -> float:
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    def lum(c):
        return 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2])

    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("theme", ["live", "live-light"])
def test_every_word_in_the_world_is_readable(scene, theme):
    """Both themes, every text role the scene actually paints.

    The light theme is where this breaks: dark backdrops flatter almost any ink, so a guard that
    only ever ran against the dark build passes while the light one is unreadable.
    """
    playwright = pytest.importorskip("playwright.sync_api")
    page_file = scene / f"{theme}.html"
    if not page_file.exists():
        pytest.skip(f"{theme}.html was not built")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1400, "height": 900})
        pg.goto(page_file.as_uri())
        pg.wait_for_timeout(800)
        measured = pg.evaluate(_CONTRAST_JS)
        browser.close()

    assert measured, "no text found in the scene at all — the selectors have moved"
    failures = []
    for item in measured:
        big = item["size"] >= 18 or (item["size"] >= 14 and int(item["weight"] or 400) >= 700)
        floor = AA_LARGE if big else AA_SMALL
        ratio = _ratio(item["fg"], item["bg"])
        if ratio < floor:
            failures.append(f"{item['cls']} at {item['size']:.0f}px: {ratio:.1f}:1 < {floor}")
    assert not failures, f"{theme} text below the readable floor:\n  " + "\n  ".join(failures)
