# Roadmap

Each phase ends with something usable. Tick boxes as work lands.

## Phase 0 — Understand the save format

Goal: know exactly where every piece of data we need lives in a `.eu4` file.

- [x] Confirm local saves are non-ironman text (`EU4txt` header) — game 1.37
- [x] Identify the two on-disk layouts: zip archive (manual saves) and raw text (autosaves)
- [x] Locate game install, user data folder, `continue_game.json` and localisation files
- [x] Extract a real save and map the top-level keys of `meta` and `gamestate`
- [x] Locate the player country block and list the fields needed for a summary
- [x] Locate wars and diplomacy blocks
- [ ] Map war internals (participants, war score), armies, provinces and ruler references
- [x] Document findings in [SAVE_FORMAT.md](SAVE_FORMAT.md)
- [x] Decide parsing strategy (own parser vs. existing library) — D-003, D-008
- [ ] Trim small fixtures from a real save into `tests/fixtures/`

## Phase 1 — Summary to clipboard (MVP)

Goal: `chancellor summary` prints a compact briefing of the player's situation and copies
it to the clipboard, ready to paste into any chat.

- [x] `save.loader`: find the current save (prefer `continue_game.json`, fall back to newest
  file), open zip or raw text, return `meta` + `gamestate` text
- [x] `save.parser`: parse Clausewitz text into Python structures, with lazy parsing
- [ ] `context.summarizer`: economy, military, stability/legitimacy, overextension
- [ ] `context.summarizer`: active wars with war score and participants
- [ ] `context.summarizer`: allies, rivals, subjects, neighbours with relative strength
- [ ] Map tags (`CAS`) and province ids to readable names
- [ ] `app.cli`: `summary` command with `--save` and `--copy` options
- [ ] Unit tests against fixtures; performance check on a 50 MB autosave

## Phase 2 — Chat workspace

Goal: a desktop app docked beside the game that answers questions using the latest save
as context. See [VISION.md](VISION.md) for the comfort goal.

- [x] `config`: load API key, save dir and model from `.env`
- [ ] `llm.client`: Claude API wrapper with streaming and prompt caching of the summary
- [ ] `watcher`: detect new saves and refresh the cached summary
- [ ] `app.ui`: web-based desktop window (pywebview or similar) with a chat view
- [ ] Docked layout: position EU4 as a borderless window and dock the panel beside it
- [ ] Overlay mode toggled by a global hotkey
- [ ] Show which save/date the answer is based on
- [ ] Conversation history within a session

## Phase 3 — Agent with tools

Goal: the model decides what to look up instead of receiving a fixed summary.

- [ ] `context.tools`: `get_country`, `get_province`, `get_war`, `compare_armies`, `list_neighbours`
- [ ] Tool-use loop in `llm.client`
- [ ] Mechanics reference: EU4 wiki and/or game files (`common/`) as a retrieval source
- [ ] Evaluation set of real questions with expected reasoning

## Phase 4 — Charts and insight

Goal: visual analysis of the campaign inside the workspace.

- [ ] Evaluate PDX Tools: link, embed in a tab, or reuse its open-source parsing libraries
- [ ] Charts view: income/expense breakdown, army strength, development
- [ ] Save history: index past saves and chart trends over time
- [ ] Let the model reference charts in its answers

## Phase 5 — Claude plays (experimental)

Goal: explore how far the assistant can act, not just advise.

- [ ] Advise: structured action recommendations
- [ ] Guide: exact UI steps for each recommendation
- [ ] Act: computer-use prototype that performs approved actions while the game is paused

## Ideas / later

- Ironman support via a token file
- Package as a single executable
