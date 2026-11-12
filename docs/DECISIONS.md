# Design decisions

Lightweight decision log. One entry per decision, newest last. Never rewrite an entry;
supersede it with a new one.

---

## D-001 — Python as the implementation language

**Date:** 2026-11-11 · **Status:** Accepted

Python has first-class LLM SDKs, simple GUI options, and is quick to iterate on.
The main risk is parsing speed on 50 MB saves; if it becomes a problem, the parser can be
swapped for a native library (see D-003) without touching the layers above.

## D-002 — Chat lives outside the game

**Date:** 2026-11-11 · **Status:** Accepted (refined by D-006)

EU4 mods cannot make network requests, so an in-game chat is not feasible. A borderless
always-on-top window, toggled with a hotkey, gives a near-integrated experience.

## D-003 — Parsing strategy

**Date:** 2026-11-11 · **Status:** Accepted (see D-008)

Options were a hand-written Clausewitz parser in Python, an existing Python package, or
bindings to the Rust `eu4save` / `jomini` crates. Chosen: a hand-written Python parser.
It has no native build step, handles the quirks seen in real saves, and is fast enough
when combined with lazy parsing (D-008). Native bindings stay an option if full-world
analysis (Phase 4 charts) needs it.

## D-004 — Non-ironman only, initially

**Date:** 2026-11-11 · **Status:** Accepted

Ironman saves need a non-public token file. The developer plays non-ironman, so text
saves cover the real use case.

## D-005 — Web-based desktop UI

**Date:** 2026-11-11 · **Status:** Proposed

The UI must host a chat, charts (Phase 4) and possibly an embedded PDX Tools tab. A
web-based desktop shell (e.g. `pywebview`) keeps the backend in Python while giving access
to mature web chart libraries. A native toolkit such as Tkinter would make charts and
multi-view layouts much harder. Final choice of shell to be made at the start of Phase 2.

## D-006 — Docked layout instead of embedding the game window

**Date:** 2026-11-11 · **Status:** Accepted

The goal is to have game and chat feel like one window. Reparenting or capturing the
DirectX game window is fragile (input, fullscreen, latency). Instead, the app arranges EU4
as a borderless window and docks its own panel beside it, with an optional hotkey overlay.

## D-007 — Computer use as the only channel for acting in-game

**Date:** 2026-11-11 · **Status:** Accepted (long-term)

Mods cannot communicate with external processes, so any "Claude plays" feature must act
through screen-level control (screenshots and input). It is scoped as an experimental
final phase, with explicit player approval for every action.

## D-008 — Lazy parsing of the gamestate

**Date:** 2026-11-11 · **Status:** Accepted

A full parse of a late-game gamestate takes ~19 s in pure Python, mostly in the
per-token loop. A brace-counting pre-pass (regex, C speed) can locate every block without
building it. `parse_lazy` parses one level and leaves nested blocks as `LazyBlock`
objects that parse on demand. Reaching the player's country costs ~2.4 s in the worst
local save, instead of 19 s, and the result is identical to a full parse.

## D-009 — Query tools before the chat; one implementation for CLI and agent

**Date:** 2026-11-12 · **Status:** Accepted

Real questions are about any country, possible wars and the wider world, not only the
player's own realm. Each kind of question becomes a query function returning structured
data (dataclasses). The CLI renders the data as Markdown for copy-paste use now. The chat
agent (Phase 4) calls the same functions as tools, so the player never supplies context
by hand. Building the tools first means the chat is useful from its first version.
Phases were reordered: query tools (2), game knowledge (3), chat with agent (4).

## D-010 — Game files as the primary knowledge source

**Date:** 2026-11-12 · **Status:** Accepted

Long-term planning needs game content: missions, events, decisions and formables. The
player's own installation provides it in the exact installed version, and in the
Clausewitz syntax the existing parser reads. The EU4 wiki can lag behind patches, so it
is a secondary source, used for strategy and mechanics explanations.

## D-011 — Alliance networks per major power, not transitive blocs

**Date:** 2026-11-12 · **Status:** Accepted

Chaining alliances transitively merged rivals such as France and Austria into a single
"bloc" of about 100 countries, which says nothing about a real war. The world overview
instead shows each major power's direct network: the power, its fighting subjects, its
allies and their fighting subjects. Roughly, that is who shows up when the power goes to
war. Major powers are the player, the great powers and the largest armies.

## D-012 — Three-valued condition evaluation instead of a full trigger engine

**Date:** 2026-11-12 · **Status:** Accepted

Formable nations and decisions are gated by game conditions, and EU4 has hundreds of
trigger types. Re-implementing all of them is not realistic. `context.conditions`
evaluates the ~60 that matter for planning (tags, cultures, religions, technology,
provinces and cores, subjects, HRE, flags, geography, province counts, scripted
triggers…). Everything else returns `None` ("unknown"), and unknowns propagate with
proper three-valued logic, so a missing core province is still reported with certainty.
Checklists mark unknown requirements `[?]` for the player to verify in game.

Measured on the local saves, 6% of formable-nation requirements end up unknown, and
37% across all decisions (mostly estate and parliament conditions).

## D-013 — Cache parsed game data on disk; keep the save uncached

**Date:** 2026-11-12 · **Status:** Accepted

Localisation, missions, decisions, modifiers and rules take ~5 s to parse on every run, but
they only change when the game is patched. Their parsed form is pickled in the user's
cache folder. The cache key is a fingerprint of every source file's path, size and mtime,
plus the package version, so any patch or upgrade rebuilds it automatically.
`chancellor clear-cache` or `CHANCELLOR_NO_CACHE=1` are the escape hatches. Pickle is
acceptable because only this program writes those files, for the same user.

The save itself is not cached: it changes every time the player saves. Instead, the lazy
parser records the first two levels of blocks in a single pass, so opening `countries`
no longer rescans 70% of the file. That halves save preparation (4.2 s → 2.3 s). A
"C-level" brace scanner (split, accumulate, bytes.find) was tried and measured: it was no
faster than the token scan, so it was dropped.
