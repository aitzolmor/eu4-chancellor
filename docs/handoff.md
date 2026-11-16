# Handoff — project state

Snapshot for picking the work up in a new session. Written on **2026-11-13**, last
updated on **2026-11-14** after the second play-test (PRs #1–#40 merged;
490 tests passing, CI green on Ubuntu and Windows with Python 3.11 and 3.12).

Read [CLAUDE.md](../CLAUDE.md) first for the conventions, then this file. For depth:
[ROADMAP](ROADMAP.md) (task list), [DECISIONS](DECISIONS.md) (D-001 to D-032),
[SAVE_FORMAT](SAVE_FORMAT.md) (verified save facts), [ARCHITECTURE](ARCHITECTURE.md).

## What we were doing

Phase 4: getting the Chancellor in front of the player while they play.

- **2026-11-13, tools:** the first play-test through the MCP tools found ten issues;
  all are fixed (#15–#22): armies at sea counted, HRE section with the next imperial
  reform, aggressive expansion, overextension and monarch power, truces (estimated end,
  D-017), targets defended by the player's own allies (D-018), "any N of M provinces"
  for region missions, triggers in words (D-019).
- **2026-11-13, desktop app** (`chancellor app`, [UI_DESIGN](UI_DESIGN.md)): hybrid chat
  with the paid API only on the player's switch (D-020), pywebview panel (D-021) with
  live refresh and alerts, docking on two screens, and on one screen a native, round
  floating icon that opens the panel and Claude Desktop as an overlay (D-022, D-023).
  Verified live by the user, with EU4 running as administrator; on 2026-11-14 also
  over Miracast.
- **2026-11-14, second play-test** on the 1483 save: the advice improved, and seven new
  findings went to ROADMAP (coalition risk first).
- **Ideas recorded, not scheduled:** goal-based watches, goals and a campaign journal
  for the panel (ROADMAP, *Ideas / later*).
- **First live API call (2026-11-14):** one question from the panel's API chat cost
  $0.031 (Sonnet 5.5, `medium`); the budget counter worked. The answer's facts were
  right but its advice was generic (ROADMAP, *Answer quality of the chat*). The user's
  key is in `.env`; ask before any call: it is billed. **The user's API balance is 5 EUR and will
  not be topped up** (D-028): test with fakes, and have the user run any live question
  from their own terminal.

## What is finished

| Phase | Delivered | Commands / modules |
| --- | --- | --- |
| 0 — Save format | Loader for zip and plain-text saves, Clausewitz parser with lazy parsing, documented format | `save.loader`, `save.parser`, `docs/SAVE_FORMAT.md` |
| 1 — Briefing | Markdown briefing of the player's country, copied to the clipboard | `chancellor summary --copy` |
| 2 — Query tools | Briefing of any country with its relation to the player; war feasibility; world overview | `country`, `war-check`, `world` |
| 3 — Game knowledge | Mission trees with progress and real modifier bonuses; formable nations and decisions with a three-valued requirement checklist; expansion targets crossing missions, formables, claims and cores with war odds; on-disk cache of game data | `missions`, `decisions`, `targets`, `clear-cache` |
| 4 — Chat (partial) | API agent with streaming tool loop; terminal chat; MCP server and config helper | `chat`, `mcp`, `mcp-config` |

Shared foundations:

- `context.campaign.Campaign`: cached, lazy view of a save, plus country lookup by tag or
  accent-insensitive name.
- `game.localisation`: Spanish names, with the language detected from `settings.txt`.
- `context.conditions`: evaluator for about 60 EU4 triggers.
- `context.script`: readable descriptions of game script.
- `context.tools.Toolbox`: the six queries as tools; the API agent and the MCP server
  share it.

## What is missing

In priority order. The full list is in [ROADMAP](ROADMAP.md).

1. **Second play-test findings** (done on 2026-11-14 on the 1483 save; list in
   [ROADMAP](ROADMAP.md) under *Play-test findings (2026-11-14)*). The first round's
   fixes held up. The worst new gap, coalition risk, is fixed (D-024): war checks and
   targets read the AE the target and its neighbours hold. The two checklist findings
   are fixed too: unmet requirements are shown whole, and another country's mission
   is named with its owner. The smaller findings are fixed as well (D-025); only
   the AE estimate of a peace deal is left.
2. **First live run of `chancellor chat`** with the real API key, to tune the system
   prompt and effort. It spends money, so ask the user before running it.
3. **Data gaps that limit advice:**
   - available casus belli (not found in the save yet);
   - income and expense breakdown (ledger category indices not mapped);
   - estate and parliament conditions in the checklists (about 37% `[?]` outside the
     formables, about 6% for the formables).
4. **Usability:**
   - run from any folder (today `.env` is read from the working directory);
   - the desktop app: designed on 2026-11-13 ([UI_DESIGN](UI_DESIGN.md), D-020,
     D-021); steps 1-4 are built: the panel window (`chancellor app`), the save
     watcher with live refresh, alerts, and docking: on two screens, or a floating icon
     with an overlay on one (D-022), both verified live (docking also over
     Miracast), step 5, quick questions and a hotkey (D-026), and step 6, the API
     chat tab on a budget (D-028). Next is step 7, charts (Phase 5).
5. **Later phases:**
   - goal-based watches, goals and a campaign journal for the panel (an idea, recorded
     in ROADMAP under *Ideas / later*; not scheduled);
   - an evaluation set of real questions;
   - Phase 5: charts and trends across saves, PDX Tools evaluation;
   - Phase 6: Claude acting in-game through computer use.

## Decisions and why

The full reasoning is in [DECISIONS.md](DECISIONS.md).

| # | Decision | Why |
| --- | --- | --- |
| D-001 | Python | LLM SDKs, quick iteration; the parser could be swapped later |
| D-002/006 | Chat outside the game, docked beside it | Mods cannot make network requests; embedding a DirectX window is fragile |
| D-003/008 | Own parser, lazy parsing | A full parse of a 57 MB gamestate takes ~19 s; lazy parsing reaches the player's country in ~2 s |
| D-004 | Non-ironman only | The ironman token file is not public; the user plays non-ironman |
| D-005 | Web-based desktop UI (proposed) | Charts and multi-view layouts; still to confirm when the window is built |
| D-007 | Computer use for in-game actions | It is the only channel into the running game |
| D-009 | Query tools before the chat; one implementation for CLI and agent | Questions concern any country and the world; the chat must be useful from day one |
| D-010 | Game files as the primary knowledge source | They match the installed 1.37 exactly; the wiki lags behind patches |
| D-011 | Alliance networks per major power | Transitive "blocs" merged rivals such as France and Austria |
| D-012 | Three-valued condition evaluation | EU4 has hundreds of triggers; unknowns must not hide certain failures |
| D-013 | Cache game data on disk, not the save | Game files change only with patches; the save changes on every save |
| D-014 | Targets count ownership conditions only | Counting every mention marked all of Castile as a target |
| D-015 | Terminal chat first, manual streaming loop, caching, refusal fallbacks | Stream text, validate tool inputs, recover from tool errors; the window reuses the agent |
| D-028 | API chat on a budget: Sonnet 5.5 at `medium`, priced responses, $0.50 per question, $5 in all | The user's API balance is 5 EUR and will not be topped up |
| D-016 | MCP server alongside the API chat | Uses the Claude subscription instead of per-token billing; same `Toolbox` |

## Traps we hit

### The save and the game data

- **Paths.** Documents is redirected to OneDrive (`OneDrive\Documentos\…`), and several
  old EU4 installs exist on the machine; only `C:\Games\Europa Universalis IV` counts.
  `continue_game.json` is a better guide to the current campaign than file modification
  times.
- **Two save layouts.** Manual saves are zip archives; autosaves are plain text with
  meta and gamestate concatenated. Saves are Windows-1252 encoded, not UTF-8.
- **Parser surprises.**
  - Indentation is unreliable, and the key `map_area_data{` appears without `=`.
  - The parser groups repeated keys, which loses their order. That is why `if`/`else`
    chains are reassembled specially.
  - `complex_dynamic_effect` stores script *inside quoted strings*.
- **Save semantics.**
  - Diplomatic links stay in the save after their `end_date`; filter them with
    `Campaign.active_links`.
  - `coalition_against_us` is repeated once per member.
  - Rulers are references into the country history, and elective monarchies use
    `foreign_heir`; 0.6% of rulers still go unresolved.
  - War score and casus belli are not in the save. Truces are, in `active_relations`
    (`truce=yes`, `last_war`), but without an end date (estimated, D-017).
- **Localisation.** Stat names live under `MODIFIER_X`, `x` or `X`, and some of those are
  long descriptions. Texts contain colour codes and `[Root.…]` placeholders.

### Performance

- Never fully parse every country (tens of seconds). Use `quick_stats` (regex) and
  `exists()` (regex) instead.
- A "C-speed" brace scanner was measured and was not faster, so it was dropped. Opening
  the save is now ~2.3 s.
- The `anthropic` SDK takes **~10 s to import** on this machine, so it is imported lazily
  and only `chat` pays for it.

### Tooling on this machine

- **The Bash tool mangles backslashes** in inline Python heredocs (`\n`, `\\`). Write
  multi-line fix scripts to a file in the scratchpad and run that file instead.
- **PowerShell 5.1 breaks `gh pr create --body`** when the body contains quotes. Always
  use `--body-file`.
- **`gh` is not on the Git Bash PATH.** Prefix commands with
  `export PATH="$PATH:/c/Program Files/GitHub CLI"`.
- **Merging and CI.**
  - Merging a stacked PR's base with `--delete-branch` closed the dependent PR (#3).
    Open follow-up PRs against `main` instead; their diff shrinks once the base merges.
  - The repository does not allow auto-merge, and `--admin` merges are blocked.
  - GitHub's Windows runners sometimes queue for 30+ minutes.
- **Tests and the cache.** The tests used to write into the real game-data cache;
  `tests/conftest.py` now redirects it to a temporary folder.
- **Previewing the panel page.** The in-app browser shows `file://` pages as static
  snapshots without their CSS and JS. Serve `src/chancellor/app/web` with
  `python -m http.server` (a local `.claude/launch.json`, not committed) and inject a stub
  `window.pywebview.api` that returns a real `PanelApi.status()` result.
- **Testing the real window.** `webview.start(func)` runs `func` in a thread once the
  window is up; it can read the page with `window.evaluate_js(...)` and close it with
  `window.destroy()`, which makes a quick end-to-end check.
- **Screens.** The main laptop is 2240×1400 at 150% scaling (about 1493×933 logical);
  window placement must be per-monitor DPI aware.
- **Docking across scalings.** A window moved from the 150% screen to a 100% one rescales
  itself on arrival (`WM_DPICHANGED`), undoing a size set in the same call: Claude
  Desktop ended at 2/3 size. `_Win32.place` moves first, then sizes with the invisible
  borders of the new DPI (11 px at 150%, 7 px at 100%).
- **EU4 runs as administrator here.** With an elevated window in front, Windows hides
  the mouse buttons from normal programs: `GetAsyncKeyState` read nothing while EU4 was
  active, though the cursor position and clicks on our own windows still arrived. The
  floating icon's page reports press and release for that reason (D-022). Check with a
  token query (`TokenElevation`) when input behaves differently with the game in front.
  `RegisterHotKey` is not affected: the panel's hotkey works with the elevated game in
  front (verified 2026-11-14).
- **Claude Desktop virtualises `%LOCALAPPDATA%`.** It is an MSIX (Store) app, so every
  process started from it, Claude Code's shells included, reads and writes
  `AppData\Local\Packages\Claude_…\LocalCache\Local\…` instead of the real folder.
  A `chancellor app` started from Claude Code and one started from the user's own
  terminal therefore see different `state.json` files (and caches). Have the user
  start the app from their own terminal for any test that spans two runs.
- **EU4 ignores outside resizing.** `SetWindowPos` on its borderless SDL window changes
  nothing; never plan a layout that needs the game to shrink.
- **Win32 handles from ctypes.** `HWND_TOPMOST` is `-1` and must reach `SetWindowPos`
  as a pointer-sized value, so `_Win32` declares `argtypes` on its own `WinDLL`
  instances (never on the shared `ctypes.windll`, which pywebview uses too). Without
  them the call failed silently and the overlay was neither on top nor resized.
- **pywebview and hidden windows.** A window created with `hidden=True` is centred on
  its first `show()`, which can land after our move; the overlay places it once
  visible, then again 0.3 s later. Destroying windows from inside a pending `js_api`
  call hangs; `PanelApi.quit` does it on another thread, and the panel's `closing`
  handler must not cancel a quit.
- **Web views cannot be round.** WebView2 paints outside a window region
  (`SetWindowRgn`), so a pywebview window always shows square corners; transparency and
  colour keys do not help. Anything that must not be rectangular is a native layered
  window (D-023). Check such claims by sampling screen pixels with and without the
  window (`GetPixel` on the screen DC), as was done here.
- **Areas with a colour.** In `map/area.txt` some areas start with `color = { ... }`;
  the parser then keeps the bare province ids under the empty key `""`. `_geography`
  dropped them until D-031, so 50 areas (Austria's own among them) and every region built
  from them were short of provinces. `CACHE_FORMAT` was bumped so old caches rebuild.
- **The wiki blocks automated access.** Its API and anonymous `Special:Export` answer
  with a bot challenge or 403. Never work around that: the user exports pages in their
  own browser while logged in, and `chancellor wiki-import` indexes the XML. Many titles
  are redirects (Aggressive expansion → Relations); after an export, list the redirect
  targets it lacks and have the user export those too. Run the import from the user's
  terminal, not from Claude Code: the index lives in `%LOCALAPPDATA%`, which Claude
  Desktop's container virtualises (see above).
- **Checking game mechanics.** The game's tooltips show the exact figure and its parts
  (technology cost, monthly power, leader pool), and the user can read them without
  knowing strategy. That is how D-029 was calibrated: a level's year is the block after
  the current level in `common/technologies`, years ahead are whole years, the
  neighbour bonus is a flat -5%, ideas only discount their own category, and
  corruption and innovativeness are cut to a thousandth. Ask for a screenshot of the
  tooltip rather than guessing.
- **Diagnosing the live app.** A run that logs the button state, cursor, foreground
  window and icon actions (only on change) found the elevation problem in one try;
  keep that approach for input issues.
- **"Claude Desktop" is this app.** The `claude.exe` window docking moves is the same
  Claude app the Code tab runs in, so a live docking test moves the conversation window.

### MCP and Claude Desktop

- **mcp 2.x API.** `FastMCP` was renamed `MCPServer` (`mcp.server.mcpserver`), and
  attributes are snake_case (`server_info`, `is_error`).
- **Errors.** Only `ToolError` messages reach Claude; other exceptions are masked.
- **stdio.** The server talks over stdio, so nothing may print to stdout.
- **Configuration.**
  - Claude Desktop is installed as a Microsoft Store (MSIX) package, so edit its config
    through *Settings → Developer → Edit Config*.
  - `mcpServers` must be a **top-level** key.
  - Close the app fully before saving, or it may overwrite the file.
  - The server gets its paths from `env` in that config, because `.env` is not found from
    Claude Desktop's working directory.

### Secrets

The API key lives only in the git-ignored `.env`. Never print it, and never put it in
`mcp-config` output or in commits.

## Next step

Done on 2026-11-14: docking over Miracast works (the second laptop is an ordinary
extended monitor, 1366×768 at 96 DPI), and the second play-test is recorded
(`notes/2026-11-14-playtest.md`, findings in ROADMAP).

1. **Every second play-test finding is fixed** (coalition risk D-024, ally reliability
   D-025, checklists, formables, display), and the war check now estimates the AE a
   conquest would add (D-030). A third play-test can wait for a later save.
2. **Desktop app:** step 5 (quick questions, hotkey) is done (D-026), and so are the
   docking follow-ups (D-027: screens dropping and returning, the icon's place, the
   overlay side, the "…" menu), and step 6, the API chat tab on a budget (D-028:
   Sonnet 5.5, $0.50 cap per question, $5 in all).
3. **Answer quality** (ROADMAP): the first live answer gave generic advice. The plan
   agreed with the user (2026-11-14): Claude stays the orchestrator and the "expert" is
   knowledge it can look up, not another model. First layer done: game mechanics
   computed in the tools (D-029, monarch power; D-030, AE of a conquest). **Check D-030
   in the user's next war**: the peace screen shows the AE of each demanded province;
   compare with `war-check` for that enemy (the distance falloff and the reach are the
   wiki's 1.24 rules). Development cost is done too (D-031, matches the tooltips).
   **Coring cost** waits for a tooltip at the user's next conquest (the wiki's Core page,
   checked for 1.37, now describes its modifiers). The wiki is a searchable source too
   (D-032, `search_wiki`); next, judge it with the play-test questions in Claude
   Desktop, then player feedback on answers. The user is no expert, so validate numbers against
   the game's tooltips (they can read those), not strategy. Any live API check needs
   the user's go-ahead; mind the 5 EUR balance.
4. Remaining data gaps (casus belli, income breakdown), or the watches idea, whichever
   the play-test shows matters more.
5. **Real-time data** (discussed 2026-11-14, not started): monthly autosaves already
   feed the panel; a small mod writing values to `game.log` with the `log` effect is
   worth a prototype; reading the game's memory is ruled out.

**Tip:** a Claude Code session on this machine has the `eu4-chancellor` MCP tools too
(`mcp__eu4-chancellor__*`), so play-tests can be run from here at no API cost. They read
the newest save, so ask the user to save first when the campaign has moved on.
