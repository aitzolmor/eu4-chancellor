# Handoff — project state

Snapshot for picking the work up in a new session. Written on **2026-11-13** and updated
the same day after the first play-test (PRs #1–#21 merged, the next imperial
reform in review; 347 tests passing, CI green on Ubuntu and Windows with Python 3.11 and 3.12).

Read [CLAUDE.md](../CLAUDE.md) first for the conventions, then this file. For depth:
[ROADMAP](ROADMAP.md) (task list), [DECISIONS](DECISIONS.md) (D-001 to D-023),
[SAVE_FORMAT](SAVE_FORMAT.md) (verified save facts), [ARCHITECTURE](ARCHITECTURE.md).

## What we were doing

Phase 4: getting the Chancellor in front of the player while they play. The last two
pieces merged were:

- **`chancellor chat` (#12):** a terminal chat on the Anthropic API (billed per question).
  The user has created an API key and put it in the local `.env`. **No live API call has
  been made yet.**
- **`chancellor mcp` (#13):** an MCP server, so Claude Desktop can use the same tools with
  the user's Claude subscription (no API key, no per-question billing). The user added it
  to `claude_desktop_config.json`. The first attempt failed because the `mcpServers`
  block had been pasted *inside* `"preferences"` and wrapped in extra braces. After the
  fix, the server is **confirmed working from the Claude app**: `get_save_status`
  returned `Austria1475_06_21.eu4`, 1475.6.21, Austria (HAB).

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

1. **Second play-test** (first play-test done on 2026-11-13, findings list in
   [ROADMAP](ROADMAP.md) under *Play-test findings*). Done: armies at sea are counted
   (#15), the briefing shows the HRE (#16), aggressive expansion, overextension and
   monarch power (#17), war checks and targets know about truces (#18) and flag
   targets defended by the player's own allies (#19); targets say "any N of M
   provinces" for counted mission conditions (#20); common triggers read as words
   (#21, D-019) and the HRE section shows the next imperial reform. Every finding is
   done; the second play-test checks whether the advice actually improved.
2. **First live run of `chancellor chat`** with the real API key, to tune the system
   prompt and effort. It spends money, so ask the user before running it.
3. **Data gaps that limit advice:**
   - available casus belli (not found in the save yet);
   - income and expense breakdown (ledger category indices not mapped);
   - advisors and generals in the briefing;
   - estate and parliament conditions in the checklists (about 37% `[?]` outside the
     formables, about 6% for the formables).
4. **Usability:**
   - run from any folder (today `.env` is read from the working directory);
   - the desktop app: designed on 2026-11-13 ([UI_DESIGN](UI_DESIGN.md), D-020,
     D-021); steps 1-4 are built: the panel window (`chancellor app`), the save
     watcher with live refresh, alerts, and docking: on two screens, or a floating icon
     with an overlay on one (D-022), both verified live. Next is step 5, quick
     questions.
5. **Later phases:**
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
| D-015 | Terminal chat first, manual streaming loop, `claude-opus-5-5`, effort `high`, caching, refusal fallbacks | Stream text, validate tool inputs, recover from tool errors; the window reuses the agent |
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

1. **Second play-test through MCP, planned for the morning of 2026-11-14.** The user
   cannot play before the evening of 2026-11-13; they will advance the campaign that
   night and save, so the play-test runs on a newer save than 1475.6.21. Before it:
   - check `get_save_status` shows the new save (ask the user to save if not);
   - ask the user to restart Claude Desktop fully, so its MCP server loads the new code.

   Ask the same questions as the first play-test (`notes/2026-11-13-playtest.md`): how
   the campaign is going, attacking Venice, the next 50 years, forming Germany or
   Austria-Hungary, where to expand. Note what changed, what is still wrong, and turn new
   findings into roadmap items. A Claude Code session can run it with the
   `mcp__eu4-chancellor__*` tools; Claude Desktop shows how Claude chains them itself.
2. **Desktop app, build order step 5** ([UI_DESIGN](UI_DESIGN.md)): quick questions
   (copy a question to the clipboard and bring Claude Desktop to the front), and a
   hotkey for the overlay. Docking still needs: Miracast, a screen appearing or dropping
   while the app runs, and remembering the icon's position. The API chat mode stays off
   unless the player switches it on (D-020).
3. With the user's go-ahead for the cost, the first live `chancellor chat` run, compared
   with the answers given through MCP.
4. Remaining data gaps (casus belli, income breakdown, advisors and generals) or the
   docked window, whichever the play-test shows matters more.

**Tip:** a Claude Code session on this machine has the `eu4-chancellor` MCP tools too
(`mcp__eu4-chancellor__*`), so play-tests can be run from here at no API cost. They read
the newest save, so ask the user to save first when the campaign has moved on.
