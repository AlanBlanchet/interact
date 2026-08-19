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
def browser():
    """ONE browser for the module.

    `asyncio_mode = "auto"` puts every test inside an event loop, and Playwright's sync API
    refuses to open a second context inside one — so a per-test `sync_playwright()` passes when
    run alone and errors in a full run, which is the worst kind of test. It is also one chromium
    instead of six on a machine with no swap.
    """
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def page(scene, browser):
    # Explicitly NOT reduced motion: every animation in this file is the thing under test, and a
    # harness that quietly disables them reports "identical" no matter what broke.
    pg = browser.new_page(viewport={"width": 1100, "height": 800},
                          reduced_motion="no-preference")
    pg.goto((scene / "live.html").as_uri())
    pg.wait_for_timeout(600)
    yield pg
    pg.close()


# NO traveller-colour tests here any more, and the reason is worth keeping.
#
# They guarded a real bug: a walking character was a CLONE of its sprite, reparented onto a
# traffic layer outside its pod, so it lost the `--accent` it inherited from there and wore
# another team's colour for the whole walk. Invisible in every still frame of a standing team.
#
# The tile rewrite deleted the mechanism. A body now owns a tile coordinate and the element ITSELF
# moves — `wp-travelling`, `makeWalker` and the copied-property list are all gone from sim.ts. So
# the defect is not fixed, it is unreachable: there is no clone and no reparenting for a custom
# property to fall out of. A test for a mechanism that does not exist passes forever and protects
# nothing, which is the same trap as the contrast guard that ERRORED instead of failing when its
# element was renamed.
#
# What replaced the coverage: `test_every_word_in_the_world_is_readable` measures what actually
# paints in both themes, and the movement tests below check that bodies genuinely move.

def test_saying_something_makes_the_sender_walk(page):
    """"Place the characters on it and make them move (when interacting)."

    The previous version of this asserted that two COURIER SPRITES did not overlap. The tile
    rewrite deleted couriers-as-sprites: a note now makes the SENDER cross the building to deliver
    it, which is the behaviour actually asked for. The old test skipped silently once `.wp-errand`
    stopped existing — a skip is not a pass, and a test that can only skip protects nothing.
    """
    moved = page.evaluate(
        """() => {
          const wp = window.__wp;
          if (!wp || !wp.note || !wp.bodies) return {error: 'the sim exposes no messaging seam'};
          wp.tick.on = false;
          if (wp.clearNotes) wp.clearNotes();
          const ids = Object.keys(wp.bodies);
          if (ids.length < 2) return {error: 'need two people for one to walk to the other'};
          // Two people as far apart as the roster allows, so a delivery is a real journey.
          const from = ids[0], to = ids[ids.length - 1];
          const before = {x: wp.bodies[from].x, y: wp.bodies[from].y};
          wp.note(from, to, 'come and look at this');
          // Step the engine forward rather than waiting on its own schedule — racing a
          // spontaneous trip is exactly how the last movement bug stayed invisible.
          for (let t = 0; t < 40; t++) wp.step(performance.now() + t * 120);
          const after = {x: wp.bodies[from].x, y: wp.bodies[from].y};
          return {from, to, before, after,
                  travelled: Math.abs(after.x - before.x) + Math.abs(after.y - before.y)};
        }"""
    )
    assert "error" not in moved, moved.get("error")
    assert moved["travelled"] > 0, (
        f"{moved['from']} said something to {moved['to']} and never left its tile "
        f"({moved['before']} -> {moved['after']}) — interaction has to cause movement")


# --- The chat panel's reliability, in a real browser -----------------------------------------
#
# "I want to be able to chat just like in claude code in vscode. And i still have none of that
# that is actually reliable." Two failures that destroy typed text, both invisible to any test
# that only builds strings:
#   - a failed send used to clear the box before the send was confirmed;
#   - a streaming update must not rebuild the document under someone who is mid-sentence.


@pytest.fixture(scope="module")
def chat_page(browser):
    """The chat document, rendered from source with the host's API stubbed."""
    render = Path("/tmp/chatrender.ts")
    if not render.exists():
        pytest.skip("the chat render fixture is not present")
    subprocess.run(["node", "--experimental-strip-types", str(render)],
                   check=True, capture_output=True)
    pg = browser.new_page(viewport={"width": 420, "height": 600})
    pg.goto("file:///tmp/chat/dark.html")
    pg.wait_for_timeout(300)
    yield pg
    pg.close()


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
def test_every_word_in_the_world_is_readable(scene, browser, theme):
    """Both themes, every text role the scene actually paints.

    The light theme is where this breaks: dark backdrops flatter almost any ink, so a guard that
    only ever ran against the dark build passes while the light one is unreadable.
    """
    page_file = scene / f"{theme}.html"
    if not page_file.exists():
        pytest.skip(f"{theme}.html was not built")
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    pg.goto(page_file.as_uri())
    pg.wait_for_timeout(800)
    measured = pg.evaluate(_CONTRAST_JS)
    pg.close()

    assert measured, "no text found in the scene at all — the selectors have moved"
    failures = []
    for item in measured:
        big = item["size"] >= 18 or (item["size"] >= 14 and int(item["weight"] or 400) >= 700)
        floor = AA_LARGE if big else AA_SMALL
        ratio = _ratio(item["fg"], item["bg"])
        if ratio < floor:
            failures.append(f"{item['cls']} at {item['size']:.0f}px: {ratio:.1f}:1 < {floor}")
    assert not failures, f"{theme} text below the readable floor:\n  " + "\n  ".join(failures)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_the_rail_stays_readable_too(browser, theme):
    """The same measurement, on the panel rather than the world.

    The rail grew two new text roles after its last contrast check — the per-row action glyphs
    and the brain badge — which is exactly how a surface drifts under a floor: not in one big
    change, but one small addition at a time, each looking fine against a dark backdrop.
    """
    fixture = Path("/tmp/rail") / f"{theme}.html"
    if not fixture.exists():
        pytest.skip("the rail render fixture is not present")
    pg = browser.new_page(viewport={"width": 292, "height": 460})
    pg.goto(fixture.as_uri())
    pg.wait_for_timeout(250)
    measured = pg.evaluate(_CONTRAST_JS.replace('[class^="wp-"], [class*=" wp-"]',
                                                ".scope,.counts,.who,.note,.chip,.act,.brain"))
    pg.close()

    assert measured, "no text found in the rail — the selectors have moved"
    failures = [
        f"{i['cls']} at {i['size']:.0f}px: {_ratio(i['fg'], i['bg']):.1f}:1"
        for i in measured
        if _ratio(i["fg"], i["bg"]) < (AA_LARGE if i["size"] >= 18 else AA_SMALL)
    ]
    assert not failures, f"rail {theme} below the readable floor:\n  " + "\n  ".join(failures)


@pytest.mark.parametrize("theme", ["live", "live-light"])
def test_no_two_words_in_the_world_are_drawn_on_top_of_each_other(scene, browser, theme):
    """At a real team's density, in both themes.

    The complaint that started this rewrite was partly that text out-massed the characters. It
    still does when two long activity strings land in the same room: "reviewing the diff a…"
    over "benchmark harness di…" is not a legible workplace, it is a collision.

    Measured over EVERY text-bearing leaf. A previous version of this scoped by class and
    compared three header elements while the character labels went unchecked — a measurement that
    reports zero because it looked in the wrong place is worse than none.
    """
    page_file = scene / f"{theme}.html"
    if not page_file.exists():
        pytest.skip(f"{theme}.html was not built")
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    pg.goto(page_file.as_uri())
    pg.wait_for_timeout(2500)          # let the cast settle where it actually stands
    result = pg.evaluate(
        """() => {
          const boxes = [];
          for (const el of document.querySelectorAll('*')) {
            const t = (el.textContent || '').trim();
            if (!t || el.children.length) continue;
            const r = el.getBoundingClientRect();
            if (!r.width || !r.height) continue;
            boxes.push({t: t.slice(0, 24), x: r.left, y: r.top, w: r.width, h: r.height});
          }
          const hits = [];
          for (let i = 0; i < boxes.length; i++)
            for (let j = i + 1; j < boxes.length; j++) {
              const a = boxes[i], b = boxes[j];
              const ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
              const oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
              // A couple of pixels of antialiasing overlap is not a collision.
              if (ox > 2 && oy > 2) hits.push(`"${a.t}" over "${b.t}"`);
            }
          return {count: boxes.length, hits};
        }"""
    )
    pg.close()
    assert result["count"] > 10, "almost no text found — the scene did not render"
    assert not result["hits"], (
        f"{theme}: {len(result['hits'])} labels drawn over each other:\n  "
        + "\n  ".join(result["hits"][:8])
    )
