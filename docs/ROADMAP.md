# Roadmap

Each phase ends with something usable. Tick boxes as work lands.
Phases were reordered on 2026-11-12 (D-009): query tools and game knowledge come before
the chat, so the chat agent has something worth calling from day one.

## Phase 0 — Understand the save format

Goal: know exactly where every piece of data we need lives in a `.eu4` file.

- [x] Confirm local saves are non-ironman text (`EU4txt` header) — game 1.37
- [x] Identify the two on-disk layouts: zip archive (manual saves) and raw text (autosaves)
- [x] Locate game install, user data folder, `continue_game.json` and localisation files
- [x] Extract a real save and map the top-level keys of `meta` and `gamestate`
- [x] Locate the player country block and list the fields needed for a summary
- [x] Locate wars and diplomacy blocks
- [x] Map war internals, armies, estates, relations and ruler references
- [ ] Map advisors, ledger category indices and province internals
- [x] Document findings in [SAVE_FORMAT.md](SAVE_FORMAT.md)
- [x] Decide parsing strategy (own parser vs. existing library) — D-003, D-008
- [ ] Trim small fixtures from a real save into `tests/fixtures/`

## Phase 1 — Summary to clipboard (MVP) ✅

Goal: `chancellor summary` prints a compact briefing of the player's situation and copies
it to the clipboard, ready to paste into any chat.

- [x] `save.loader`: find the current save (prefer `continue_game.json`, fall back to newest
  file), open zip or raw text, return `meta` + `gamestate` text
- [x] `save.parser`: parse Clausewitz text into Python structures, with lazy parsing
- [x] `context.summarizer`: economy, military, stability/legitimacy, overextension
- [x] `context.summarizer`: active wars with sides and war goal (war score is not in the save)
- [x] `context.summarizer`: allies, rivals, subjects, neighbours with relative strength
- [x] Map tags (`CAS`) and province ids to readable names (`game.localisation`)
- [x] `app.cli`: `summary` command with `--save`, `--copy`, `--output`, `--language`
- [x] Unit tests against fixtures; checked on all 23 local saves (≤2.6 s, ≤1.2k tokens)
- [ ] Income/expense breakdown by category
- [ ] Advisors and generals in the briefing

## Phase 2 — Query tools

Goal: context about *any* country or question, not just the player. Every query is a
function returning structured data, rendered as Markdown by the CLI and later exposed to
the chat agent as a tool (D-009).

- [x] `context.campaign`: shared, cached access to a loaded save (countries, wars, names)
- [x] Resolve countries by tag or display name, accent- and case-insensitive
- [x] `chancellor country <name>`: the briefing from any country's perspective, including
  its relation to the player
- [x] `chancellor war-check <name>`: who would defend the target (allies, guarantors,
  overlord, subjects, Emperor, coalitions), combined strength of each side, shared allies
- [x] War check: truces, with an estimated end date (D-017)
- [ ] War check: casus belli available and AI willingness to answer calls to arms
- [x] `chancellor world`: great powers, rankings, alliance networks, major wars, unions, HRE
- [ ] Structured return types (dataclasses) shared by CLI rendering and agent tools
  (done for `war-check` and `world`; briefings still render directly to Markdown)
- [ ] Run from any folder (user-level config instead of `./.env` only)

## Phase 3 — Game knowledge

Goal: the assistant knows the game's content and can cross it with the campaign state.

- [x] Parse mission trees from `missions/` (requirements, rewards, claims granted)
- [x] Parse decisions and formable nations from `decisions/`
- [x] Condition evaluator with three-valued logic (`context.conditions`): ~60 country and
  province conditions, scripted triggers, geography, culture/religion groups
- [x] `chancellor decisions [<country>] [--formables]`: visible decisions with a met / not
  met / unchecked requirement checklist
- [x] Cache parsed game files on disk, and scan two levels of the save in one pass
  (`decisions` 10.3 s → 6.2 s; other commands 4–5 s, now dominated by the save scan)
- [ ] Evaluate mission triggers to tell "available" from "completable now"
- [ ] Index events and idea groups from `events/` and `common/`
- [x] `chancellor missions [<country>]`: mission tree with completion status from the save
- [x] Readable trigger/effect descriptions (`context.script`), localised names and tooltips
- [x] Resolve modifier effects (`common/event_modifiers`, triggered modifiers) so rewards show
  their real bonuses (99.9% of mission modifier grants)
- [x] `chancellor targets`: provinces wanted by available missions, visible formables, claims
  and cores, grouped by owner, with a war check against each (favourable / even / hard)
- [ ] Wiki lookup as a complementary source for strategy and mechanics

## Phase 4 — Chat workspace with agent

Goal: a desktop app docked beside the game where Claude answers questions and gathers its
own context with the Phase 2–3 tools. See [VISION.md](VISION.md) for the comfort goal.

- [x] `config`: load API key, save dir and model from `.env`
- [x] `llm.client`: Claude API agent with streaming, prompt caching, adaptive thinking,
  refusal fallbacks and a validated tool-use loop
- [x] Expose Phase 2–3 queries as tools (`context.tools`, six tools)
- [x] `chancellor chat`: terminal chat; reloads the save when the game writes a new one and
  tells the model earlier results may be stale
- [x] `chancellor mcp`: MCP server so Claude Desktop uses the same tools with a Claude
  subscription (no API key, no per-question billing); `chancellor mcp-config` prints the
  Claude Desktop entry
- [ ] First live run with a real API key; tune the system prompt and effort
- [x] Desktop app design: hybrid chat (D-020), pywebview shell (D-021), layout and views
  in [UI_DESIGN.md](UI_DESIGN.md)
- [ ] `app.ui`: pywebview panel with the header (country, date, save) and key numbers
- [ ] `watcher`: background save watching with live refresh of the panel (the terminal chat
  checks before each question)
- [ ] Alerts: truces ending, coalition and AE, overextension, imperial reform ready, new
  missions or formables
- [ ] `app.layout`: docked layout (EU4 borderless, panel and Claude Desktop beside it) and
  undock
- [ ] Quick questions (copy to Claude Desktop, or send to the API tab) and the overlay hotkey
- [ ] API chat tab behind the player's chat-mode switch (D-020), with a session counter of
  questions and tokens; conversation history within a session
- [ ] Evaluation set of real questions with expected reasoning

### Play-test findings (2026-11-13, Austria 1475 save, through the MCP tools)

- [x] Count armies carried by fleets: they sit inside `navy` blocks, so briefings, war
  checks and target odds missed them (Ottomans showed 31 regiments instead of 47)
- [x] Briefing: the country's role in the HRE (Emperor, elector or member), imperial
  authority, reforms passed and which candidate each elector backs
- [x] HRE: the next imperial reform, what it grants and the authority it needs
  (`game.imperial_reforms`)
- [x] Briefing: aggressive expansion held against the country (top holders, coalition
  threshold, status) and overextension shown even at 0%
- [x] Briefing: monarch power (adm/dip/mil points)
- [x] War check and targets: truces (D-017); the Ottomans were the top target although a
  peace was signed with them on the save date
- [x] Targets and war check: flag owners defended by the player's own allies (Aragón is
  defended by the ally Castilla; that war would break the alliance) (D-018)
- [x] Targets: when a mission needs N provinces of a region, say "N of M" instead of
  presenting the whole region (Relaciones ibéricas needs 4 Iberian provinces), and
  whether it is one of several ways to complete it
- [x] Checklists: describe the common trigger keys in words (`junior_union_with: ROOT`,
  `NOT: num_of_cities: 40`) (D-019)
- [ ] Decision titles built by scripted localisation (`[Root.GetActsOfUnionDecisionTitle]`)
  still fall back to the key ("force british union debate"); the heading's "forms …"
  says what it does

## Phase 5 — Charts and insight

Goal: visual analysis of the campaign inside the workspace.

- [ ] Evaluate PDX Tools: link, embed in a tab, or reuse its open-source parsing libraries
- [ ] Charts view: income/expense breakdown, army strength, development
- [ ] Save history: index past saves and chart trends over time
- [ ] Let the model reference charts in its answers

## Phase 6 — Claude plays (experimental)

Goal: explore how far the assistant can act, not just advise.

- [ ] Advise: structured action recommendations
- [ ] Guide: exact UI steps for each recommendation
- [ ] Act: computer-use prototype that performs approved actions while the game is paused

## Ideas / later

- Ironman support via a token file
- Package as a single executable
