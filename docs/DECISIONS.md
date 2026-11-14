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

**Date:** 2026-11-11 · **Status:** Superseded by D-021

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

## D-014 — Expansion targets only count ownership conditions

**Date:** 2026-11-13 · **Status:** Accepted

Mission and formable conditions mention provinces and regions for many reasons (culture,
religion, trade, a capital's area). Counting every mention marked whole countries as
targets, e.g. all of Castile for a dynastic mission. `targets` therefore only extracts
ownership: `owns`-style conditions, province counts filtered by area or region, and
province or geography scopes that check `owned_by`, `is_core` or similar. Continents,
superregions and any scope over 120 provinces are too broad to be targets.

Targets are ranked in odds tiers (2x or better, 1x–2x, below 1x) and then by
development. Ranking by raw odds alone would put one-province minors above rich,
slightly harder targets. Hard targets get their own section so that a coalition-protected
mission target (e.g. Venice) stays visible.

## D-015 — Chat agent: terminal first, manual streaming loop, Opus 5.5

**Date:** 2026-11-13 · **Status:** Accepted

- **Terminal first.** `chancellor chat` ships the whole agent (tools, loop, save
  following) before any window code. The desktop window (D-005, D-006) will reuse
  `ChancellorAgent` unchanged.
- **Manual loop instead of the SDK tool runner.** The loop streams answer text to the
  player while it is generated, validates every tool input before running it (inputs
  stream eagerly and are not validated by the API), turns bad input and unknown countries
  into `is_error` tool results the model can recover from, and caps the rounds per
  question. The runner is a beta helper; the loop is about 60 lines.
- **Request settings.** `claude-opus-5-5` (override with `CHANCELLOR_MODEL`), adaptive
  thinking (always on for this model) at effort `high` (`CHANCELLOR_EFFORT`), top-level
  prompt caching (the static system prompt and tool list form the cached prefix),
  server-side refusal fallbacks (`fallbacks: "default"`), and an append-only history so
  thinking blocks stay valid.
- **Save changes mid-conversation** are announced with a mid-conversation system message
  after the next question, which keeps the cached prefix intact.
- **The SDK is imported lazily.** Importing `anthropic` takes ~10 s on the development
  machine, so only `chancellor chat` pays for it.

## D-016 — MCP server for Claude Desktop alongside the API chat

**Date:** 2026-11-13 · **Status:** Accepted

The API chat bills every question, while a Claude subscription (Pro, Max, …) already
covers Claude Desktop, which can call local tools through the Model Context Protocol.
`chancellor mcp` serves the same `Toolbox` over stdio, so both front ends share every
query, description and validation rule. Trade-offs:

- **Subscription, not tokens.** It uses the plan's usage limits instead of per-token
  billing, and needs no API key.
- **Less control.** The model, effort and system prompt belong to Claude Desktop. The
  server's `instructions` and the tool descriptions carry the guidance.
- **Freshness per call.** The server reloads whenever the newest save's path or mtime
  changes, and keeps game data loaded across reloads. There is no "the player saved"
  note in the conversation; `get_save_status` lets the model confirm what it is reading.
- **Configuration by environment.** Claude Desktop starts the server from its own
  working directory, so `.env` is not found. `chancellor mcp-config` prints the entry
  with absolute paths in `env`, and never includes the API key.

Both front ends stay: the API chat is the base for the docked desktop window, while the
MCP server is the zero-cost way to use the tools today. Tools raise the SDK's `ToolError`
so Claude sees messages such as "No country named 'Narnia'"; other exceptions are masked
by the SDK.

## D-017 — Truces: estimated end date, demoted rather than hidden

**Date:** 2026-11-13 · **Status:** Accepted

The save records that a truce exists (`truce=yes` in `active_relations`, with `last_war`
and `last_warscore`) but not when it ends. The end is estimated as
`last_war + TRUCE_YEARS + SCALED_TRUCE_YEARS × warscore / 100` (5 + 10 × share, from
`common/defines.lua`). On the 1475 play-test save none of the 295 truces with a war date
had outlived that estimate. Modifiers to truce length (ideas, policies) are ignored, so
the date is always labelled an estimate.

A truce does not make a war impossible, only costly (breaking it), so:

- `check_war` keeps its forces table and puts the truce warning first; participants
  with a truce against the other side are listed in the notes, without changing their
  likelihood, because whether they may still join is not verified.
- `targets` sorts owners under a truce after every other war target instead of dropping
  them, and names the ones pushed out of the visible list.

## D-018 — Targets defended by the player's own allies rank with truced ones

**Date:** 2026-11-13 · **Status:** Accepted

An owner can be defended by one of the attacker's allies when that ally is bound to it:
its overlord, one of its subjects, or a coalition member. On the play-test save Aragón
(defended by its overlord Castilla), Navarra (Castilla) and Turingia (Sajonia) were top
war targets for Austria. The forces table already moved those allies to the defending
side, but nothing said that the war would turn an ally into an enemy.

`check_war` now lists them as `allied_defenders` with a note, and `targets` treats them
like a truce (D-017): such owners sort after every other war target and are named when
pushed out of view. Allies that are merely allied to both sides stay in "Tied to both
sides", as before.

## D-019 — Common triggers in words, the rest as script keys

**Date:** 2026-11-13 · **Status:** Accepted

`context.script` used to keep every trigger key as written (`junior_union_with: ROOT`,
`NOT: num_of_cities: 40`), on the grounds that keys are precise and the LLM knows them.
The play-test showed checklists that read poorly for the player and leave ambiguity for
the model (which country is `ROOT` inside a `Hungría:` scope?).

About 40 of the most common triggers (technology, cities, war, independence, HRE role,
unions, ownership, flags, missions, religion, culture, government, estates) are now
phrases: "Junior partner in a personal union with this country (ROOT)", "Not: 40 or more
cities". `NOT`, `OR` and `AND` read "Not", "One of", "All of". `ROOT` becomes "this
country (ROOT)", keeping the scope name so nested scopes stay unambiguous. Every other key
is kept as it is: rare triggers stay precise, and the table grows only when a play-test
shows a key that matters. `value` is not phrased because it also appears in effects and
variables.

## D-020 — Hybrid chat: Claude Desktop by default, the API only on the player's request

**Date:** 2026-11-13 · **Status:** Accepted

The vision placed an API-driven chat inside the Chancellor's window. Since D-016 the same
tools also work in Claude Desktop through MCP, covered by the player's subscription,
while the API bills every question. The desktop app is therefore hybrid:

- **By default the chat is Claude Desktop**, docked beside the game. The Chancellor's
  window does what Claude Desktop cannot: arrange the windows, show the campaign's state
  and alerts, and later charts.
- **The API chat is a mode the player switches on**, with a visible control in the
  window. It is never on by default, never chosen by the app, and never a fallback when
  Claude Desktop is unavailable. Turning it on asks for confirmation once per session,
  and while it is on the window says so and counts the questions and tokens.

`ChancellorAgent` stays the engine of the API mode; the terminal `chancellor chat`
remains for development. Details in [UI_DESIGN](UI_DESIGN.md).

## D-021 — pywebview shell with a plain web frontend

**Date:** 2026-11-13 · **Status:** Accepted (supersedes D-005)

The window needs web-grade layout and, in Phase 5, chart libraries, while the backend is
Python. Options considered:

| Shell | For | Against |
| --- | --- | --- |
| **pywebview** (Edge WebView2 on Windows) | Python in-process, small, WebView2 ships with Windows 11, frameless and on-top windows | Fewer widgets than Qt; the JS bridge is basic |
| PySide6 + QtWebEngine | Mature, rich native widgets | ~200 MB of dependencies, licensing to watch |
| Electron or Tauri | Strong tooling for web UIs | A second runtime (Node or Rust) plus a Python sidecar and IPC |

pywebview wins: one language for the backend, a light dependency, and the page talks
to Python through `js_api` calls and `evaluate_js` events. The frontend is plain HTML,
CSS and JavaScript modules with no build step; libraries are vendored so the app works
offline. If the frontend outgrows that, a bundler can be added later without touching
the backend contract. Window docking uses Win32 through `ctypes` (D-006).

## D-022 — One screen: a floating icon and an overlay, never a split

**Date:** 2026-11-13 · **Status:** Accepted (refines D-006; the icon's implementation is
superseded by D-023)

The one-screen layout planned in UI_DESIGN gave the game 70% of the screen and a column
to the panel and Claude Desktop. Tried live, it could not work:

- EU4's borderless window ignores outside resizing; it draws at the resolution set in
  the game, so the "70%" game stayed full screen on top of the column.
- Claude Desktop will not go narrower than about 600 logical pixels (903 physical at
  150%), wider than a 30% column.

So with one screen nothing is split. A small floating icon stays over the game; clicking
it opens the panel and Claude Desktop as an always-on-top column on the icon's side of
the screen, and clicking again puts them away (Claude Desktop drops behind the game).
The icon can be dragged out of the way, and is shown only while the game is in front.
With two screens, docking on the other screen stays the preferred layout.

Implementation notes that shaped it:

- **EU4 runs as administrator** on the developer's machine. While an elevated window is
  in front, Windows hides the mouse buttons' state from normal programs
  (`GetAsyncKeyState` reads nothing), but the pointer's position and the clicks on our
  own window still arrive. The icon's page therefore reports press and release, and
  Python follows the pointer in between.
- The icon window is clipped to its circle (`SetWindowRgn`), since pywebview's
  transparency does not work there, and is created with `focus=False` so clicking it
  does not take the focus from the game.

## D-023 — The floating icon is a native window, not a web view

**Date:** 2026-11-13 · **Status:** Accepted (refines D-022)

The first floating icon was a small pywebview window clipped to a circle with
`SetWindowRgn`. Screen pixels sampled with and without it showed the corners still
painted: WebView2 composites its content outside the window region, and neither
pywebview's transparency nor a colour key changed that. Windows 11's own rounded
corners do clip, but only to a small fixed radius.

The icon is now a plain Win32 layered window (`app.icon_window.FloatingIcon`) whose
pixels carry their own alpha (`UpdateLayeredWindow`), so only the circle shows; the
same sampling confirmed the corners match what is behind. It is also the cheapest
option to run: no browser process for a 64 px button. It handles the mouse itself
(left button drags or clicks, right button opens *Close Chancellor*), and those
messages arrive even while the game runs as administrator. The picture is drawn in pure
Python (`render_icon`, anti-aliased from exact distances, three cached states), so it is
tested on any platform. The panel stays a web view, where HTML is worth its cost.

## D-024 — Coalition risk is read from the AE already held, not estimated from a peace

**Date:** 2026-11-14 · **Status:** Accepted

The second play-test found the countries most outraged by Austria (Venice 74 AE,
Switzerland 83, Milan 82) ranked as the easiest targets once the old coalition had
dissolved. War checks and targets now carry a coalition risk
(`war_check.CoalitionRisk`), read from the aggressive expansion (AE) the target and its
neighbours (the save's `neighbours` list) already hold against the attacker. The
attacker's allies and subjects are left out, since they cannot join a coalition against
it.

- **High:** the target is at the coalition threshold (50, `AE_COALITION_THRESHOLD` in
  `defines.lua`), or three or more of its neighbours are.
- **Medium:** the target is at 35 or more, one neighbour is at 50, or two neighbours
  are at 35-50. A conquest usually adds tens of AE to exactly these countries, so they
  can cross 50 in a single war.
- **Low:** otherwise.

Targets with a high risk rank after every other unblocked war target, and the ones
pushed out of the table are named. The AE a peace deal would add is not estimated yet:
it depends on the casus belli, distance, culture, religion and HRE membership of every
country in range, and the casus belli is not in the save. The thresholds are a
heuristic: AI coalition decisions also weigh opinion, distance and threat, which are
not modelled.

## D-025 — Allies with a low opinion or trust are only possible participants

**Date:** 2026-11-14 · **Status:** Accepted

War checks counted every ally as "likely" to answer a call to arms. In the second
play-test Castile, with an opinion of +4 towards Austria, made up 40 of the 197
regiments on Austria's side. The AI weighs opinion and trust when it answers a call, so
an ally whose opinion of the country calling it is below 25, or whose trust is below 30,
is now "possible": it counts only in the worst case, and its role says why ("ally (low
opinion +4)"). The opinion is the save's `cached_sum` in the ally's `active_relations`;
`trust_value` is omitted at the default of 50. The same rule applies to the defender's
allies. The thresholds are a heuristic: the AI also weighs the war's odds, its own wars
and its debts, which are not modelled.

## D-026 — Quick questions copy a prompt; a system-wide hotkey opens the Chancellor

**Date:** 2026-11-14 · **Status:** Accepted

The panel's quick questions copy a full prompt to the clipboard and bring Claude Desktop
to the front; the player pastes it (Ctrl+V) and sends it. The app does not type into
Claude Desktop itself: simulated keystrokes would land wherever the focus happens to be
and could send a half-written message, while one paste keeps the player in control.
The prompts name what to look at ("expansion targets, war odds and coalition risk"),
so Claude picks the right MCP tools first time. They are in English like the rest of
the repository; Claude answers in the language the player writes in.

A system-wide shortcut, `Ctrl+Shift+Space` by default (`CHANCELLOR_HOTKEY` in `.env`),
opens and closes the overlay on one screen and brings Claude Desktop forward on two. It
is registered with `RegisterHotKey` on a thread with its own message loop, which
delivers `WM_HOTKEY` whichever window is in front: it works while EU4 runs as
administrator, unlike reading the input state (D-022). A registered hotkey is taken
before the game sees it, so a player who uses that combination in game can pick another.

## D-027 — The app follows the screens; the player picks the overlay side; a "…" menu

**Date:** 2026-11-14 · **Status:** Accepted (refines D-022)

- **Screens while running.** The app checks the number of screens every two seconds.
  When the second screen drops (a Miracast link ends), docked windows go back where
  they were, the panel hides and the floating icon takes over; when it returns, the
  overlay closes, the panel shows and docks again if it was docked. The native icon
  registers its window class once, with the first instance's window procedure, so the
  app creates one icon at start and only shows or hides it, instead of creating one
  when the mode changes.
- **The icon's place is remembered**, relative to its monitor's work area (so a change
  of resolution or scaling keeps it in the same spot), in `state.json` next to the
  cache, not inside it (`clear-cache` must not forget it). Monitor device names change
  when a display reconnects, so a place on the primary monitor falls back to whichever
  monitor is primary.
- **The overlay side is the player's choice**, not the icon's half of the screen. The
  player moves the icon out of the way of the game, and needs the overlay on the side
  where it hides the least of the interface they want to read while asking. It is
  remembered too.
- **A "…" menu** in the header holds what is used now and then: docking, the way back
  to the game, the overlay side and the hotkey. Results and errors appear in a status
  line under the header only while there is something to say. The footer is gone, so
  the overlay panel, about 350 px high on one screen, keeps room for the alerts and
  numbers.
