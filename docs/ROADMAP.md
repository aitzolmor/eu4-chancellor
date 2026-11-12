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
- [ ] War check: truces, casus belli available and AI willingness to answer calls to arms
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
- [ ] "Expansion targets" view: mission/claim targets combined with `war-check` results
- [ ] Wiki lookup as a complementary source for strategy and mechanics

## Phase 4 — Chat workspace with agent

Goal: a desktop app docked beside the game where Claude answers questions and gathers its
own context with the Phase 2–3 tools. See [VISION.md](VISION.md) for the comfort goal.

- [x] `config`: load API key, save dir and model from `.env`
- [ ] `llm.client`: Claude API wrapper with streaming, prompt caching and a tool-use loop
- [ ] Expose Phase 2–3 queries as tools
- [ ] `watcher`: detect new saves and refresh cached data
- [ ] `app.ui`: web-based desktop window (pywebview or similar) with a chat view
- [ ] Docked layout: position EU4 as a borderless window and dock the panel beside it
- [ ] Overlay mode toggled by a global hotkey
- [ ] Show which save/date the answer is based on
- [ ] Conversation history within a session
- [ ] Evaluation set of real questions with expected reasoning

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
