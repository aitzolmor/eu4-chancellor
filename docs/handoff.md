# Handoff — project state

Snapshot for picking the work up in a new session. Written on **2026-11-13**, with `main`
at `8669567` (PRs #1–#13 merged, 308 tests passing, CI green on Ubuntu and Windows with
Python 3.11 and 3.12).

Read [CLAUDE.md](../CLAUDE.md) first for the conventions, then this file. For depth:
[ROADMAP](ROADMAP.md) (task list), [DECISIONS](DECISIONS.md) (D-001 to D-016),
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

1. **Play-test with real questions** in Claude Desktop through MCP, which costs nothing
   extra. Fix whatever the answers show to be missing or wrong (see *Next step*).
2. **First live run of `chancellor chat`** with the real API key, to tune the system
   prompt and effort. It spends money, so ask the user before running it.
3. **Data gaps that limit advice:**
   - truces and available casus belli (not found in the save yet);
   - income and expense breakdown (ledger category indices not mapped);
   - advisors and generals in the briefing;
   - estate and parliament conditions in the checklists (about 37% `[?]` outside the
     formables, about 6% for the formables).
4. **Usability:**
   - run from any folder (today `.env` is read from the working directory);
   - the docked desktop window (`app.ui`, D-005/D-006) and the overlay hotkey.
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
  - War score, truces and casus belli are not in the save.
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

**Play-test the Chancellor in Claude Desktop during a real session** (no API cost):

1. Save the game. Ask the Chancellor 5–10 real questions, for example:
   - "How is my campaign going?"
   - "Is attacking Venice worth it?"
   - "What should Austria do in the next 50 years?"
   - "Can I form Germany?"
   - "Where should I expand?"
2. For each question, note:
   - which tools Claude called;
   - what it got wrong or could not answer;
   - which missing data mattered.

   Keep the notes in `notes/` (git-ignored; Spanish is fine there).
3. Turn the findings into roadmap items. Likely candidates: tool descriptions or
   `INSTRUCTIONS` wording, output length, and the data gaps listed in *What is missing*.
   Then fix the most painful one first.

After that, with the user's go-ahead for the cost, do the first live `chancellor chat`
run and compare its answers with Claude Desktop's.
