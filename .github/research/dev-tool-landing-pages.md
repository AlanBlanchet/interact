# AI-agent / browser-automation dev-tool landing pages — survey for interact's showcase

Survey of how modern AI-agent / browser-desktop automation dev tools present landing pages +
branding, to inform interact's GitHub Pages showcase + README. 8 tools reviewed. 2026-07-12.

## Peers

- **browser-use** — "Tell your computer what to do, it gets it done." Hero: 2 CTAs + 6 feature
  cards, no video. Demo: README code snippet + GIFs + model-accuracy chart. Light/dark, emoji
  headers. Hook: open benchmarks + Fortune-500 social proof.
- **Stagehand / Browserbase** — "The SDK for browser agents." Dark hero, 4 named primitives
  (act / extract / observe / agent) as icons, abstract node illustration, docs-first CTAs. Demo:
  TS `act()` + Zod-typed `extract()`. Hook: legible mental model, not a black box.
- **Steel.dev** — "A better way to take your LLMs online." Hero: GIF of an agent booking a flight
  live + throughput stats ("800B+ tokens", "<1s session start"). Black/white/gray + blue CTA.
  Hook: comparative speed metrics as proof.
- **Skyvern** — "Automate browser-based workflows with AI." Hero: HIPAA/SOC2/YC badges + logos
  before any code. Demo: 6 real-workflow GIFs + WebBench score. Hook: trust signals front-loaded.
- **magnitude** — vision-first, pixel-coordinate agent. README-only, 4 icon functions, terminal
  GIF, dark terminal framing. Hook: vision-over-DOM stated plainly as the differentiator.
- **Playwright** — multi-language install one-liner + star count + client logos (VS Code, Adobe).
  Light/dark toggle. Hook: zero-friction multi-language parity + adoption proof.
- **Puppeteer / Anthropic computer-use** (incumbent baselines) — one code example / capability
  bullets, no visual hook. Fine for incumbents, wrong for a tool still earning attention.

## Patterns worth stealing

1. **Motion as hero, not garnish** (Steel/Skyvern) — one looping GIF of interact driving a real
   app beats a static grid. (Not yet done — future win.)
2. **Named-primitive mental model** (Stagehand/magnitude) — expose interact's real tools
   (screenshot, run_actions, review_ui, verify_ui, measure_ui, transcribe, record) as
   icon-labeled primitives. ✓ done in the capability grid.
3. **The code block IS the demo** — a real MCP call → text-diff response pair is interact's most
   unique asset; nobody else returns diffs, not screenshots. ✓ done (demo terminal).
4. **A hard comparative number** — quantify the text-diff-vs-screenshot context saving
   (~50 tokens vs ~1,000+). ✓ done (metric strip).
5. **Client-parity badge row** (Playwright logos) — Claude/Cursor/VSCode/Codex/Windsurf/Zed row
   = feature + credibility together. ✓ done ("works inside").
6. **Reuse the existing mark** — the reticle-eye (`docs/assets/logo.svg` / `banner.svg`,
   `#0B0E14` bg, violet→cyan) nails 2026's dark-AI-tool register. ✓ now wired.

## Anti-patterns avoided

1. Compliance-badge wall before product proof (Skyvern) — wrong register for an open MCP tool.
2. Feature-card wall with no code/motion (browser-use homepage) — cards nobody believes unseen.
3. Generic 2026 AI template — purple-pink gradient blobs + typewriter headline. interact's
   reticle mark stays geometric, not decorative-blob.
4. Docs-only, zero visual hook — fine for incumbents, not a tool still earning attention.

## Tagline direction

"Eyes and hands for AI agents — vision-grounded control that reports what changed, not a
screenshot." Keep "MCP-native" explicit: Stagehand/browser-use are SDK-first; that's a real,
ownable category gap. → shipped as "Give your agent eyes and hands." + MCP-native subline.

## Sources (all fetched 2026-07-12)

browser-use.com + README · stagehand.dev (live-verified) + browserbase.com + README · steel.dev
+ README · skyvern.com + README · github.com/magnitudedev/browser-agent (magnitude.run
unreachable) · playwright.dev · platform.claude.com computer-use docs · pptr.dev + README.
