# Roadmap

Each phase ends with something usable. Tick boxes as work lands.

## Phase 0 — Understand the save format

Goal: know exactly where every piece of data we need lives in a `.eu4` file.

- [x] Confirm local saves are non-ironman text (`EU4txt` header) — game 1.37
- [x] Identify the two on-disk layouts: zip archive (manual saves) and raw text (autosaves)
- [ ] Extract a real save and map the top-level keys of `meta` and `gamestate`
- [ ] Locate the player country block and list the fields needed for a summary
- [ ] Locate wars, diplomacy (alliances, rivals, subjects), armies and provinces
- [ ] Document findings in [SAVE_FORMAT.md](SAVE_FORMAT.md)
- [ ] Decide parsing strategy (own parser vs. existing library) — record in [DECISIONS.md](DECISIONS.md)
- [ ] Trim small anonymized fixtures into `tests/fixtures/`

## Phase 1 — Summary to clipboard (MVP)

Goal: `chancellor summary` prints a compact briefing of the player's situation and copies
it to the clipboard, ready to paste into any chat.

- [ ] `save.loader`: find the newest save, open zip or raw text, return `meta` + `gamestate` text
- [ ] `save.parser`: parse Clausewitz text into Python structures (streaming-friendly)
- [ ] `context.summarizer`: economy, military, stability/legitimacy, overextension
- [ ] `context.summarizer`: active wars with war score and participants
- [ ] `context.summarizer`: allies, rivals, subjects, neighbours with relative strength
- [ ] Map tags (`CAS`) and province ids to readable names
- [ ] `app.cli`: `summary` command with `--save` and `--copy` options
- [ ] Unit tests against fixtures; performance check on a 50 MB autosave

## Phase 2 — Chat window

Goal: a small always-on-top window next to the game that answers questions using the
latest save as context.

- [ ] `config`: load API key, save dir and model from `.env`
- [ ] `llm.client`: Claude API wrapper with streaming and prompt caching of the summary
- [ ] `watcher`: detect new saves and refresh the cached summary
- [ ] `app.ui`: always-on-top chat window with a global hotkey
- [ ] Show which save/date the answer is based on
- [ ] Conversation history within a session

## Phase 3 — Agent with tools

Goal: the model decides what to look up instead of receiving a fixed summary.

- [ ] `context.tools`: `get_country`, `get_province`, `get_war`, `compare_armies`, `list_neighbours`
- [ ] Tool-use loop in `llm.client`
- [ ] Mechanics reference: EU4 wiki and/or game files (`common/`) as a retrieval source
- [ ] Evaluation set of real questions with expected reasoning

## Ideas / later

- Ironman support via a token file
- Historical comparison between saves ("how has my economy changed since 1500?")
- Package as a single executable
