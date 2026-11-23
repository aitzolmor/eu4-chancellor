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
37% across all decisions (mostly estate and parliament conditions). Re-measured on the
1539 save after D-066: 0% for formables, 23% for major decisions, 40% for the others
(mostly estate influence), and 21 of 83 requirements of the player's missions.

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

**Date:** 2026-11-13 · **Status:** Accepted; model, effort and limits superseded by D-028

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

## D-028 — The API chat runs on a budget: Sonnet 5.5, priced responses, hard caps

**Date:** 2026-11-14 · **Status:** Accepted (supersedes the model and effort of D-015)

The player's API balance is 5 EUR and will not be topped up. As built for D-015, one
unlucky question could have spent all of it: 64,000 output tokens per request and up to
12 tool rounds, about $15 in the worst case on Opus 5.5, with cache writes not even
counted. The chat now treats money as a hard limit:

- **Model and effort.** Claude Sonnet 5.5 at effort `medium` (the starting point the
  API guidance gives for multistep tool use on that model), at about half the price of
  Opus 5.5. Chosen by the player; `CHANCELLOR_MODEL` / `CHANCELLOR_EFFORT` still
  override it.
- **Every response is priced** from the usage the API returns, cache writes and reads
  included (`llm.cost`, prices checked 2026-11-03; an unknown model is priced like the
  most expensive one), and charged to the budget as it arrives, so spending is recorded
  even when a later request fails. A response served by a fallback model is priced as
  that model.
- **Per question.** Before every request the agent checks that its worst case (all input
  written to the cache, full output) still fits the question's cap, $0.50 by default,
  and stops the question otherwise. Requests are limited to 16,000 output tokens and a
  question to 6 tool rounds, so the worst single request on Sonnet 5.5 is about $0.17.
- **In all.** A running total in `state.json`, shared by `chancellor chat` and the
  panel, against a budget of $5 by default (a little under 5 EUR). The cap of the last
  questions shrinks to what is left; with less than a cent left the chat refuses. The
  total only knows what the app spent, so it should be set to what is left for the app.
- **The panel's API chat** (build order step 6, D-020): a mode switched on in the "…"
  menu, confirmed once per session with the model, the cap and what is spent; while it is
  on, the header shows the spending and a *Chat* tab holds the conversation, streamed as
  it is written, with the tools used and the cost of each answer. Quick questions go to
  that tab instead of the clipboard. Answers are rendered from Markdown by a small
  renderer that escapes all HTML first.

Development and tests use fake clients; live calls happen only with the player's
go-ahead, from their own terminal (the Claude Desktop MSIX container keeps a separate
`state.json`, see the handoff).

## D-029 — Game mechanics are computed in the tools, checked against the game's tooltips

**Date:** 2026-11-14 · **Status:** Accepted

The first live answer of the API chat had the facts right and the advice wrong: it
suggested spending ~390 military points on a technology that cost 1194, or on generals
the country did not need. The model filled in game rules from memory. Rather than a
second model trained on the game (no such model is known, and there is no data to train
one) Claude stays the orchestrator, and the tools state the mechanics so the advice can
rest on them.

The first mechanics are monarch power (`context.power`, rules in `game.power_rules`): the
cost of the next technology in each category with its parts, the next idea, stability,
a general, the monthly gain with its sources, the months until each technology, and the
leaders and advisors. They appear in the country briefing.

Every rule is read from the game files where it lives; the one rule that is not there
(+1 monthly power at 50 power projection) is a named constant. The numbers were checked
against the game's tooltips for Austria on 1483.3.2, and the test suite rebuilds that
case: technology 677 / 653 / 1194, +6 / +8 / +8 a month, three leaders without upkeep.
The calibration found what reading the files alone got wrong: the level bought after
level N is block N of the technology file; the game counts whole years ahead; the
neighbour bonus is a flat -5%, not -5% per neighbour; ideas only discount technology of
their own category; corruption and innovativeness are cut to a thousandth. Two parts are
still estimates and say so: technology cost changes from idea bonuses, policies,
government reforms and estate privileges are not read, and the free leader pool omits
the land force limit, so it is stated as a minimum. The months until a technology let
its ahead-of-time penalty shrink as its year approaches, which can be sooner than the
game's own estimate (it keeps today's cost).

Checking numbers against tooltips also answers how to evaluate the Chancellor without a
game expert: the player can read a tooltip even when they cannot judge a strategy.

## D-030 — The war check estimates the AE of taking the claimed provinces

**Date:** 2026-11-14 · **Status:** Accepted (completes D-024)

D-024 read the AE countries already hold but not what a conquest would add, so it could
not say how much land was safe to take. The war check now estimates it (`context.ae`,
rules in `game.ae_rules`) for the target's provinces the attacker has claims or cores
on: the base AE per province (development capped at 30, times 0.6, times the casus belli
factor: 1 for a claim, 0.25 for a core, less the attacker's prestige and administrative
efficiency), then what each country within reach receives (more for the loser's
religion and the province's culture or culture group and inside the Empire, less with
distance; two thirds for the attacker's allies, a tenth for its subjects), with the AE
it holds now and after, and who would cross 50.

The numbers come from the game files; how they combine follows the game wiki's
formula, written for 1.24. Two parts are not documented for 1.37: the distance falloff
(`1 / (1 + 0.75 x distance / 100)`, distance rounded down to hundreds and capped at 400)
and which distant countries receive nothing (here: none beyond 400 map units). The
output says so, and the estimate is to be checked against a peace deal in the player's
next war, the way D-029 was checked against tooltips.

To measure distances cheaply, `Campaign.province_owners` reads every province's owner
with a regular expression instead of parsing the provinces; an estimate takes about
three seconds. The expansion targets do not run it for every owner yet, for that cost.

## D-031 — Development costs from the map and the game's own tooltips

**Date:** 2026-11-14 · **Status:** Accepted

The briefing now lists what developing each of the country's provinces costs, cheapest
first (`context.development`). The cost is 50 points times one plus its parts: the
capital's discount, embraced institutions, the golden bull of the papacy's religion,
passed imperial reforms, country and province modifiers, the centre of trade (level 2
for the province, level 3 for its whole state), terrain, climate, prosperity, the
development already there, corruption and innovativeness. The game floors the result.

Terrain is not in the save, and it matters (mountains +35%, hills +25%). It is read
from the map as the game does (`game.terrain`): the category covering most of each
province's pixels in `terrain.bmp`, matched to `provinces.bmp` through `definition.csv`,
unless `terrain.txt` fixes it. Every second pixel in each direction is sampled; the
result takes about five seconds and is cached until the game files change.

Three rules are not in the files and were read off the tooltips for Austria in 1483:
the base of 50, the capital's discount of 0.05% per point of the country's development
(cut to a thousandth), and the growth with development already there, +3% a point from
10 and +6% from 20. Growth above 30 is assumed to rise by another 3% every ten points;
it was not seen. The golden bull applies to every country of the papacy's religion,
not only the papal controller (Austria had it while Castile controlled the Curia). The
result matches the tooltips: Vienna 59, Ostmark 53, Tirol 56.

Reading the areas for prosperity exposed a parser gap: areas written with a colour lost
their provinces (50 areas, and every region built from them). Fixing it made the
expansion targets' region counts complete (Iberia 62 provinces, not 54; Germany's
formable region 145, not 119); the cache format was bumped.

Coring cost waits for a tooltip: the one province without a core was already being
cored, and the game shows no cost breakdown then (done in D-033).

## D-032 — The wiki as a local, searchable source, from the player's own export

**Date:** 2026-11-14 · **Status:** Accepted

The answer-quality plan keeps Claude as the orchestrator; after the computed mechanics
(D-029 to D-031) comes knowledge it can look up for how mechanics work and for strategy.
No model trained on the game is known, so the source is the community wiki.

- **Getting the pages.** The wiki answers automated requests, its API included, with a
  bot challenge, and anonymous `Special:Export` with 403. The app does not work around
  that. The player, logged in, exports pages in their own browser (current revision
  only, a list of titles plus the `Guides` category) and `chancellor wiki-import` reads
  the XML. Nothing from the wiki goes into the repository; results link to their page.
- **Index.** Pages become plain sections (`wiki.wikitext`: headings kept, templates and
  markup dropped, tables as rows, the game version each section was last checked for,
  inherited from its parent section) in a SQLite FTS5 table with English stemming and
  BM25 ranking (`wiki.store`), kept with the app's state. Redirect titles are added to
  their target's title field, so "aggressive expansion" finds the section on
  "Relations". No embeddings: they would need a paid API or a heavy local model, and
  game terms match well by word. The first import (109 pages, 38 of them redirects) gave
  2030 sections in under a second and 3.4 MB; searches take milliseconds.
- **Tool.** `search_wiki` (MCP, API chat, `chancellor wiki-search`) returns the best few
  sections, cut to about 1200 characters, each with its link and checked version. The
  tool description and both system prompts say to query in English game terms, to let
  the save and the computed numbers win over the wiki, to cite the page and to flag
  sections checked for much older versions. The prompts now also say to use the computed
  mechanics instead of rules of thumb and to skip advice every player already follows.

## D-033 — Coring costs from the game files and a tooltip

**Date:** 2026-11-15 · **Status:** Accepted

The briefing now says what coring each province without a core costs, in
administrative power and months (`context.coring`, rules in `game.coring_rules`):
`10 x development (capped at 30) x (1 + parts)`, and half that for a territory. The parts
add up: war exhaustion (3% a point), corruption, innovativeness, ideas, policies,
government reforms, estate privileges, the golden bull, imperial reforms, country and
province modifiers, administrative efficiency, and a claim (-10%). The summed parts stop
at -80%. Coring takes `36 x (1 + parts)` months, between 6 and 240.

Checked against the game's tooltip for Austria in 1492, at war: Friaul (12, a territory)
61 in 37 months, Treviso (20, a territory) 102, with war exhaustion +3.1% and
innovativeness -0.7%. As in D-029, those two are cut to a thousandth. A territory has no
flag in the save: it is a province whose area holds no state of its owner.

Not seen in a tooltip yet, so taken from the files and the wiki: the half price is a
multiplier after the sum (the tooltip lists it apart), the claim discount
(`CORE_HAD_CLAIM`), the -80% floor, the cap of 30 and administrative efficiency (zero
before administrative technology 18).

## D-034 — The AE estimate, checked against a peace deal

**Date:** 2026-11-15 · **Status:** Accepted (corrects D-030)

In the user's war against Trento (1492), the peace screen for Trient (11 development)
and Celje (9), both claimed, listed the AE each country would receive and its total
after. The totals matched the AE the save holds now, so the comparison is direct. D-030
gave twice the game's figures: Munich +21.6 against +11, Venice +19.2 against +11.

Two causes, found by fitting the 17 listed countries:

- **Difficulty.** The user plays on easy, and `difficulty_easy_player` (static modifiers)
  cuts the player's AE by 33%, added to prestige's -10%. The difficulty is the first of
  the save's `setgameplayoptions` (1 = easy). It applies to the player only.
- **Distance.** The wiki's 1.24 reading rounded the distance down to hundreds, so every
  country nearer than 100 map units took the full share. The game's figures fall off
  continuously, `1 / (1 + 0.75 x distance / 100)` with the exact distance to the
  receiver's nearest province.

With both, 15 of the 17 countries land within about one AE of the game (Venice 10.6
against 11, Munich 10.4 against 11, Parma 8.1 against 9, Hesse 7.6 against 8). Two are
still high and are left open: Cilli, which lost Celje (12.7 against about 10), and
Poland, the farthest (5.2 against about 4). The game's coalition list also left out Milan
and Mantua, which hold 90+ AE, for a reason not found. The estimate stays labelled as an
estimate.

## D-035 — Wiki retrieval checked; one result per section; coring follows the Core page

**Date:** 2026-11-16 · **Status:** Accepted (refines D-032 and D-033)

The wiki's retrieval (D-032) was checked with twelve queries a model would make for the
play-test questions (reducing AE, joining coalitions, passing imperial reforms,
integrating a union, Austria's strategy, overextension, fabricating claims, war score,
coring cost, idea groups, Revoke the Privilegia, improving relations). The right
section came first for nearly all of them. One fault: a long section is indexed in
chunks of about 1500 characters, and each matching chunk came back as its own result,
so "Revoke the Privilegia" filled all three places with the same section. Search now
reads five chunks per wanted result and keeps the best chunk of each section.

Reading the results also corrected D-033. The Core page, checked for 1.37, says
administrative efficiency and a territory's half price multiply after the other
modifiers are summed, and the cost is rounded down. Administrative efficiency had been
added to the sum; it is now a factor of its own, shown after the summed parts. It is
zero before administrative technology 18, so the tooltips that D-033 matched are
unchanged. Rounding down also matches them (61.44 and 102.4); the months still round to
the nearest, since 36 x 1.024 shows as 37.

The same page lists a permanent claim at -25% and a temporary one at -10%. The save's
province block has a single `claims` list, so every claim still counts as temporary;
that and the higher cost of coring a province whose core belongs to a country with
`enemy_core_creation` ideas are on the ROADMAP.

## D-036 — Strategy tools point to the wiki in their results

**Date:** 2026-11-16 · **Status:** Accepted (refines D-032)

The first real test in Claude Desktop asked two strategy questions: whether an expansion
plan (take a province from Gelre, release it as a vassal and feed it land, then face
Naples and France) made sense, and which idea groups suit Austria now. The answers were
much better than before, but neither called `search_wiki`. Claude Desktop loads tools on
demand and picks them by their descriptions, and the briefing, targets and war check
looked like enough.

Three changes, from weakest to strongest:

- The tool's description now says when to call it (choosing idea groups, judging an
  expansion plan or war route, subjects, coalitions and AE, the Empire, estates,
  explaining a mechanic), not only what it holds.
- The MCP instructions and the API chat's system prompt say to look up how experienced
  players handle it before advising on those topics.
- While the wiki is imported, the results of `get_country_briefing`,
  `get_expansion_targets` and `check_war` end with one line naming `search_wiki` and
  example queries in English. A pointer inside a result is read at the moment the model
  plans its answer, which a description is not. Without an imported wiki the line is
  left out, so it never sends the model to a tool that would only report a missing
  index.

Whether this is enough is for the next test; forcing a search on every question would
cost time for questions the campaign's numbers already answer.

## D-037 — Idea slots in the briefing; a level's effects are in its own block

**Date:** 2026-11-16 · **Status:** Accepted (corrects D-030, D-033 and D-035)

In the second Claude Desktop test (D-036), the model had to recall at which
administrative technology each idea group slot opens before it searched the wiki for it.
The briefing now says how many slots the country has, which groups fill them, any free
slot, and the level that adds the next with the year its ahead-of-time penalty ends.
For Austria in 1519: two of two slots chosen, the next with administrative technology
10, without penalty since 1518.

The slots are `allowed_idea_groups` in `technologies/adm.txt`, and they sit in blocks 5,
7, 10, 14, 18, 22, 26 and 29: the levels the wiki's Idea groups page lists (checked for
1.36). So a level's effects are in the block at its own position, while its
ahead-of-time year is the previous block's (D-029 checked that against the game: level
7's penalty ends in 1479, block 6's year). The administrative efficiency table had
assumed block `n` was level `n + 1` and placed the 10% steps at 18, 24 and 28; the
wiki's Overextension page gives 17, 23 and 27, matching the blocks. It now does too.
That changes AE and coring costs only from administrative technology 17; the checks in
D-034 and D-033 were at level 6. The cache format was bumped.

Absolutism also adds administrative efficiency (+0.3% a point), as do a few government
reforms; neither is counted yet (ROADMAP).

## D-038 — Player ratings of answers are set aside

**Date:** 2026-11-16 · **Status:** Set aside (an idea kept, not planned)

The answer-quality plan ended with player feedback: a thumbs up or down with a note on
each answer, to find bad advice and turn each complaint into a fix. The user declined
it. They are not an expert in the game, so a correct answer they do not expect could be
rated as wrong, and the ratings would pull the Chancellor towards what the player
already believes instead of what is right.

The approach that has worked stays the way to judge answers: check numbers against the
game's own tooltips and screens, which the player can read without knowing strategy
(D-029, D-031, D-033, D-034), and take strategy from the wiki (D-032, D-036). Ratings
could come back if the Chancellor gets players who know the game well, or as a way to
report a factual error the player can show (a tooltip, a screen), not a judgment on
advice.

What the player wants is better captured as context than as ratings: their goals,
preferences and limits per campaign (ROADMAP, *Ideas / later*).

## D-039 — The player's context, kept per campaign outside any chat

**Date:** 2026-11-16 · **Status:** Accepted

Every new chat knows the campaign, because the tools read the save, but nothing about
the player: what they want, what they rule out, what they already decided. A long chat
that reaches its limit loses all of it, and so does a change of client or model. The
Chancellor now keeps it (`player.context`):

- **What:** per campaign, goals, wants and limits ("preference"), decisions taken and
  notes; per player, what they say about themselves ("not an expert"). Each entry is
  one short statement in the player's words, with the in-game date of the save it was
  recorded with and an id.
- **Two tools**, shared by the MCP server and the API chat: `get_player_context`, which
  the instructions and the system prompt ask the model to read at the start of a
  conversation, and `update_player_context` (add, remove, replace), the only tool that
  writes. The model records only what the player states or explicitly agrees to, never
  its own inferences or suggestions, and tells the player what it recorded.
  `chancellor player-context` shows the context and removes a wrong entry.
- **Which campaign:** the save's `campaign_id` is not stable. The user's Austria game
  carried four ids between 1455 and 1519, a Castile game five, each covering a run of
  saves. A save is matched by id first; an unknown id goes to the campaign of the same
  country whose first recorded date is not later than the save's (the latest of them if
  several), and the id joins it on the next write. The output says when a campaign was
  matched that way. A new game of the same country starts in 1444, before any recorded
  date, and stays apart. Two games of one country played side by side could still be
  confused; that is rare enough to accept for now.
- **Where:** a JSON file in the game's user data folder
  (`...\Europa Universalis IV\eu4-chancellor\player_context.json`), not under
  `AppData`. Claude Desktop is a Store app whose processes see a private copy of
  `AppData`, so the MCP server it starts and the panel or CLI started from a terminal
  would read different files. The game's user folder is shared by all of them (and
  synced with OneDrive here). Reading never creates the file; writes go through a
  temporary file.

Ratings of answers were set aside (D-038); this is how the Chancellor learns what the
player wants instead. It is also the base the goal-based watches in the ROADMAP need.

## D-040 — Planning tools end with a line on the player's context

**Date:** 2026-11-16 · **Status:** Accepted (refines D-039)

The first test of the player's context in Claude Desktop went half well. In a new chat
the player set out their plans (Gelre as a vassal, then Naples and France) and asked for
an opinion; the answer used the war check and the expansion targets but recorded
nothing. In a second new chat the model read the context, found it empty, looked the
plans up in Claude Desktop's own earlier chats, answered from them and then recorded
two goals, faithful to what the player had said.

It is the pattern D-036 found for the wiki: Claude Desktop loads tools on demand and
follows what it reads while planning its answer; the server instructions asking it to
record weigh less than a line in a result. So the tools used to plan (the briefing,
expansion targets, war check, missions and decisions) now end with one line: what is
recorded for the campaign ("2 goals, 1 wants and limits recorded ... follow them"), or
that nothing is and that goals, wants, limits or decisions the player states in the
conversation are to be recorded. The line reads the small context file on each call.

## D-041 — Watches: "tell me when ..." checked on every save

**Date:** 2026-11-16 · **Status:** Accepted (builds on D-039)

The panel's alerts repeat what the game shows and know nothing of the player's plans.
The player's context (D-039) says what they want; watches say when the moment has come.

- **A watch** is the player's words plus conditions the model builds with
  `create_watch` from a closed list of 24 metrics, all read from the save
  (`player.watches`): the player's or any country's treasury, manpower (and its
  percentage), monarch points, stability, war exhaustion, overextension, prestige,
  technology, development, regiments; the AE a country holds against another, how many
  countries hold 50+, coalition members; the war check's odds; at war, truce, alliance,
  existence; the in-game year. Numbers take `>=` or `<=`, the rest `is` true or false.
  All conditions must hold. The tool description asks the model to make vague words
  concrete and to tell the player the thresholds it chose; the reply shows each
  condition's current value.
- **War odds** are the attacker's likely regiments over the defenders' worst case, the
  cautious reading of the war check (D-025), so "France is weak" is not announced on
  allies who may not come.
- **Firing.** Watches are checked when the panel reads a new save and whenever the
  planning tools or `get_player_context` run. A watch fires once, on the first check
  where every condition holds, and keeps the in-game date of that save; with neither
  the panel nor a chat running, it fires at the next check, dated by that save.
- **Where it shows.** A fired watch leads the panel's alerts, with a × to clear it, and
  the planning tools' last line (D-040) names it so the model tells the player. The
  panel also gained a *Your plan* section: goals, wants and limits, decisions and the
  waiting watches, each removable, which was the open item of D-039.
- **Storage.** Watches live with the campaign's entries in the player's context file and
  share its ids, so `update_player_context` removes either. A watch cannot be replaced:
  the model removes it and sets a new one.

First test in Claude Desktop: "tell me when France is weak enough to attack, or I
am strong enough to face it" became one watch, war odds against France >= 1.5 with no
truce (1.06 now), and the model explained that the odds rise either way, so one
condition covers both halves. The panel showed it under *Your plan*. Its first
`create_watch` call failed, though: the MCP tool declared `conditions` as a list of
plain dictionaries, so the client saw no fields and guessed. The MCP schema now types a
condition (`WatchCondition`: metric, op as `>=`, `<=` or `is`, value, country, other),
and conditions forgive common slips: numbers and true/false written as text, `>` for
`>=`, `=` for `is`.

Conditions only combine with "and"; "or" is left out until a request needs it.

Left for later (ROADMAP): a badge on the floating icon and a Windows notification while
the overlay is closed, metrics for events (an ally declaring war, a ruler dying), and the
campaign journal.

## D-042 — A fired watch is noticed on one screen and on two

**Date:** 2026-11-16 · **Status:** Accepted (completes D-041)

A watch exists to interrupt the player, but a fired one only showed inside the panel. On
one screen the panel is hidden behind the floating icon while the game runs, so "France
is weak" could go unseen; on two screens the panel is in view, but nothing draws the eye
to it while the player looks at the game.

- **One screen:** the floating icon gets a red dot (the panel's alert colour, with a navy
  rim so it stands out on the gold ring) while any fired watch is waiting to be cleared.
  The dot sits inside the disc, because the native layered window (D-023) only paints
  the circle. It goes away when the player clears the watch with its ×.
- **Two screens:** when a new watch fires, the docked panel's taskbar button and caption
  flash (`FlashWindowEx`, flashing until the window comes to the front), the signal
  Windows uses for a window that wants attention. A watch already announced does not
  flash again on later saves.
- **In the page:** a fired watch heads the alerts framed in red, in both layouts.

The panel works this out each time it reads a save (`PanelApi._announce`). A Windows
notification (toast) was left out: Windows can hold notifications back while a game is
in front, and the dot and the flash are where the player already looks. It stays an
option if the live test shows these are missed.

## D-043 — The campaign journal: a snapshot per save, compared save to save

**Date:** 2026-11-16 · **Status:** Accepted

Every tool reads one save, a picture of one moment, so nothing knew that a war started
two saves ago, a province was lost or an alliance ended, and a new chat could not
answer "what has happened lately?". The Chancellor now keeps a journal
(`player.journal`).

- **A snapshot per save read.** Each time the MCP server or the panel reads a new save
  (the shared `CampaignProvider`), and when `chancellor journal` runs, it records the
  player's country: key numbers (treasury, income, expenses, loans, manpower,
  regiments, development, provinces, stability, prestige, war exhaustion,
  overextension, technology, great power rank, countries at 50+ AE), the provinces with
  their names and which lack a core, wars, allies, subjects, rivals, truces, coalition
  members, ruler and heir, idea groups, the Emperor and the passed imperial reforms.
  One per in-game date; a read of the same date replaces it. Taking one costs about a
  second (the AE scan), on a load that already takes about two.
- **Changes save to save.** Comparing consecutive snapshots gives the journal's lines:
  provinces gained, lost or cored; wars begun and ended; allies, subjects, rivals,
  truces and coalition members gained or lost; a new ruler or heir; ideas and
  technology taken; a new Emperor or imperial reform; and one line for the numbers that
  moved. Snapshots dated after the save being read are ignored, so reloading an older
  save shows the history up to it.
- **Where it shows.** `get_campaign_journal` (MCP and API chat; the prompts point to it
  for "what happened"), the planning tools' last line ("Since the previous save
  (1519.1.1): 3 changes"), *Since your last save* in the panel, and
  `chancellor journal`.
- **Storage.** `journal.json` next to the player's context, outside `AppData` for the
  same reason (D-039), keyed by a stable campaign key the context now keeps (the first
  campaign id, or country and first date), so a campaign whose id changes keeps one
  journal; reading a save is enough to start a campaign's record. Every snapshot keeps
  its numbers, the base for trends across saves in Phase 5; only the latest 24 keep
  the lists, so a long campaign of monthly autosaves stays small (seven saves: 10 KB).

Checked on seven real saves of the user's Austria, from 1505 to 1519 under two campaign
ids: one journal, with the conquest of Istria, Padua and Welsch-Bern cored, the alliance
with Savoy ending, Maximilian I succeeding Ladislaus, an imperial reform, technology
and ideas taken, and the war for Milan beginning and ending. In Claude Desktop, after the
user played on and asked what had happened, the model called `get_campaign_journal` and
its account matched the game.

The steps are as fine as the saves read: with monthly autosaves and the panel open, a
month; otherwise from one chat to the next. Watches on events from the journal (an ally
at war, a ruler dying) are left for later.

## D-044 — A probe mod for data the save lacks, read from game.log

**Date:** 2026-11-17 · **Status:** Prototype; the channel works (2026-11-20), war score and casus belli to check

"Real-time data" turned out to be two different needs. Freshness is mostly a setting:
the user's autosave is yearly (`settings.txt`), and monthly autosaves would make the
panel, watches and journal monthly without any code. What no setting gives is data the
save does not hold: the war score of the player's wars and the casus belli available,
gaps since Phase 2.

Mods cannot make network requests, and reading the game's memory was ruled out on
2026-11-14. The one channel out is the `log` effect, which writes to `logs/game.log`
while the game runs. The game files show what a mod can build on: `on_monthly_pulse`
exists and is empty in 1.37; `log` strings take localisation like `[Root.GetName]`;
`[Root.<variable>.GetValue]` shows a variable in localisation; `export_to_variable`
takes `value = treasury` or `value = trigger_value:<trigger>`; and the game's own events
compare war score with `war_score_against = { who value }`.

The probe (`live.probe`, written by `chancellor probe install` into the game's `mod`
folder) hooks `on_monthly_pulse` with a hidden event for the player's country that only
sets its own variables and logs `CHANCELLOR|...` lines, answering in one session:

1. Does the monthly pulse run it? A heartbeat line with the year and month.
2. Does a log line show a variable? The treasury, which the save has too, as a control.
3. Can the war score be read? Directly (`trigger_value:war_score`, which may not exist)
   and by a ladder of `war_score_against` checks every 5 points against each enemy.

`chancellor probe read` (`live.gamelog`) answers each question from the log
(Windows-1252, read whole: it restarts empty with each game start). Costs to weigh once
it works: the player installs and enables a mod, which a patch can break; casus belli
cannot be listed, only checked one type and one country at a time.

**First session (2026-11-20, 1534.07 to 1534.11, at peace).** The user starts `eu4.exe`
without the launcher, so the mod was enabled by `dlc_load.json` in the game's user
folder (`{"enabled_mods":["mod/chancellor_probe.mod"],"disabled_dlcs":[]}`), which the
game reads at start. Answers: (1) yes, one heartbeat a month, on the country's own pulse
day (22nd or 26th), with the month's name in the game's language; (2) yes, the treasury
with three decimals (438.574 on 1534.10.22; the 1534.11.1 save had 451.047); `error.log`
has nothing from the mod. (3) is still open: at peace there is no enemy for the ladder,
and the direct value printed 0. Each line carries the game date (`EVENT [1534.07.22]:`),
which the reader now keeps.

**Casus belli added.** Each month the mod checks, for every neighbour, rival (both
ways) and holder of a claim or core of the player, each casus belli type in the game's
`common/cb_types` (100 in 1.37; `chancellor probe install` reads them, with a short
built-in list when the game folder is unknown) with
`has_casus_belli = { type target }`, a trigger the game's own decisions use (Austria's
personal union checks). It logs the countries checked (`cbtarget`) and each type found
(`cb`); the reader keeps the latest month. Open question: whether that trigger sees the
casus belli the game derives on the fly (claims, cores, rivals) or only the ones events
and missions add; the diplomacy screen is the reference.

**Second session (2026-11-20, 1535.01 to 1535.04).** It does see them. Each month 40
countries were checked and 18 had at least one casus belli, the same three months
running. Against the diplomacy screen, which the user read for five countries:

| Country | Diplomacy screen | Mod |
| --- | --- | --- |
| France | Conquest, Imperial ban, Imperial campaign, Humiliate | `cb_conquest`, `cb_imperial_ban`, `cb_imperial_ban_incident`, `cb_humiliate_rotw` |
| Poland | Humiliate; several Conquest of Hungary's | `cb_humiliate_rotw` |
| Liège | three Conquest | `cb_conquest` |
| Teutonic Order, Lübeck | none | not checked (none of the target rules matched) |

The player's own casus belli matched exactly (the rival one is `cb_humiliate_rotw`,
"Humillar a su rival", not `cb_humiliate`). What the mod missed were the subjects':
an overlord can declare with a subject's casus belli, and the screen lists them. The
mod now checks each subject too (`every_subject_country`, the subject kept as an event
target, `subcb` lines), against neighbours of the player or of the subject, the
player's rivals and holders of the player's claims or cores.

**Third session (2026-11-20, 1535.04).** The subject check works: six subjects
checked, two with casus belli. Hungary's conquest of Poland, which the screen showed,
is there (`cb_conquest`), with Hungary's conquest and crusade against the Ottomans and
conquest against the Papal States, and Albania's core, conquest and crusade against
the Ottomans and `cb_heretic` against Ragusa. `error.log` has nothing from the mod, so
the event target and `is_neighbor_of = event_target:...` are accepted. Liège's "three
Conquest" were one conquest casus belli covering three claimed provinces, which matches
the mod's one `cb_conquest`; which provinces it covers comes from the save's claims.
Every casus belli the user read on the screen is now accounted for.

## D-045 — Trend charts from the campaign journal, drawn as plain SVG

**Date:** 2026-11-17 · **Status:** Accepted

The vision's second secondary goal is charts in the workspace; what was missing was
data over time, and the campaign journal (D-043) now keeps every read save's numbers.

- **Charts tab.** The panel gains a tab beside *Campaign* (the *Chat* tab still only
  appears in API mode): six small line charts, one measure each so no chart has two
  y-scales: treasury; income and expenses together, since they share a unit; regiments;
  manpower; development; countries at 50+ AE. The journal's main events (wars begun
  and ended, new rulers, provinces gained or lost) are dots on each time axis, with
  their text on hover. A crosshair and tooltip follow the pointer, the charts redraw
  to the panel's width, and a table holds the same numbers. A new save read while the
  tab is open redraws it.
- **Plain SVG, no library** (`charts.js`), so the panel stays offline with nothing
  vendored (D-021). The marks follow the data-viz guidance used for this project: 2px
  lines, hairline solid grids, text in text colours, a legend for the one two-series
  chart. The two series colours are the reference palette's dark blue and orange,
  validated against the panel's surface (#162139): every check passes, CVD separation
  26.8.
- **Backfill.** The journal only starts with the first save read, so
  `chancellor journal --backfill` lists the country's saves by `campaign_id` with
  their date ranges, and `--ids` reads the groups picked, oldest first, into the
  current campaign's journal (`Toolbox.remember_other`). The player picks because the
  game cannot tell: one campaign carried five ids from 1455 to 1525, and an earlier
  Austria game (1447–1449) sits just before them. About 7 seconds a save.
- **For the model.** `get_trends` returns the same numbers as a table of up to 12
  dates with the main events, for "how is my economy doing?".

Checked in the browser with 21 real saves of the user's Austria (1455–1525) backfilled
into a temporary journal: the conquests of 1492 and 1505, the jump in development from
380 to 645 around 1523, and a month of 352 ducats in expenses in 1525, which flattens
the income chart's scale; the tooltip gives the numbers. The income and expense
breakdown by category and a world view (PDX Tools) are still open.

First test in Claude Desktop: "how has my economy evolved, and how can I improve it?"
did not call `get_trends`; the model compared 1519 with 1525 from an earlier chat it
found, and searched the wiki for trade. As with D-036 and D-040, the planning tools'
last line now says how many saves the journal holds and to use `get_trends` for how
the economy, army or growth evolved. The answer also named a gap: the tools say nothing
about trade (nodes, power shares, merchants), though the save holds it.

## D-046 — Trade from the save's nodes and the game's node map

**Date:** 2026-11-17 · **Status:** Accepted

Asked how to earn more from trade at Venice, the model had to ask the player for their
share of power in each node and where their merchants were; the tools said nothing about
trade, though the save holds it.

- **From the save** (`context.trade`): the `trade` block has a node per trade node with
  its value (`current + outgoing`) and everyone's power (`total`), and an entry per
  country with its power, the base from provinces and light ships, the ships
  protecting trade, a merchant (`has_trader`; `type=1` steers, otherwise it collects),
  the home node (`has_capital`) and what it collects there (`money`). Parsing it whole
  takes about half a second.
- **From the game files** (`game.trade_nodes`): which nodes feed which, from
  `common/tradenodes`, so the report can say whether each node's trade can reach the
  home node and how many steps away, and which feeders hold no power of the country.
  The save does not record which way a steering merchant pushes; the report says so.
- **Where it shows.** `get_trade` lists the home node (and whether it is an end node),
  the share and income there, the merchants, the light ships, a table of the nodes
  ordered home, feeders by distance, then the rest, the feeders without power and the
  embargoes. The player's briefing ends with one line on it, and the prompts point to
  it for trade.

On the user's Austria in 1525: home node Venice, an end node, with 46% of its power and
8.62 ducats a month collected; merchants collecting at Venice and steering at Vienna;
six light ships at Venice; Vienna (19%), Pest (7%) and Alexandria (3%) feeding it; and
embargoes from the Ottomans, Great Britain, France and Newfoundland. Asked again in
Claude Desktop, the trade question was answered from `get_trade`.

## D-047 — `chancellor setup` finds the paths and writes a user-level config

**Date:** 2026-11-17 · **Status:** Accepted

The commands read their paths from `.env` in the folder they ran from, so they only
worked from the project's folder, and a new user had to find and type the game's
installation and their save folder. For a project meant to be tried by others, that was
the first obstacle.

- **Discovery** (`discovery`): the game is looked for in Steam's libraries (the
  registry gives Steam's folder; `steamapps/libraryfolders.vdf` lists the libraries),
  among Windows' installed programs (an `InstallLocation` named like the game, which
  covers GOG and other installers), and in usual folders on every drive (`Games`,
  `GOG Games`, `SteamLibrary`, Steam under Program Files). A folder counts when it has
  the executable and `common`; with several (old installs linger), the newest version
  in `launcher-settings.json` wins and the rest are listed. The player's folder is
  *Documents*/Paradox Interactive/Europa Universalis IV, with *Documents* asked of
  Windows (`SHGetKnownFolderPath`), since it is often redirected to OneDrive. The
  language comes from the game's `settings.txt`.
- **User config:** `chancellor setup` checks what it found (the version, how many
  saves, the current one, the language, whether the wiki is imported) and writes
  `EU4_GAME_DIR`, `EU4_SAVE_DIR` and `EU4_LANGUAGE` to `~/.eu4-chancellor/config.env`,
  keeping any other keys there. `load_settings` reads it last: environment variables,
  then `./.env`, then the user's config, so development setups keep working. It lives
  in the home folder, not `AppData`, which Claude Desktop's processes see a private copy
  of. `--check` writes nothing; `--game-dir` and `--user-dir` override the search.
  Tests point `CHANCELLOR_CONFIG` at a temporary file so a real config never leaks in.

On the user's machine the game was found among installed programs in `C:\Games` (not in
a Steam library), version 1.37, and the data folder under OneDrive, in 0.2 seconds;
afterwards `chancellor summary` worked from a folder without `.env`.

## D-048 — Comparing the player with their rivals over time

**Date:** 2026-11-17 · **Status:** Accepted (extends D-043 and D-045)

The charts showed the player's own numbers; whether they are ahead of or behind their
rivals was the question they could not answer.

- **Snapshots** now keep, for the player's rivals and the great powers, six numbers each
  (development, regiments, income, treasury, provinces, manpower; `country_numbers`),
  plus who the rivals and great powers were; and, for the neighbours and the 30
  largest countries, development, regiments and income. Rivals change during a game
  (the user pointed out that replacing Poland would leave the new rival without a
  history), so tracking a wide set means a new rival nearly always has one.
- **Size:** 55 countries a save made the user's journal 109 KB for 21 saves. Trimmed
  snapshots keep the other countries' numbers once an in-game year, so monthly
  autosaves over a whole campaign stay around 2 MB; the comparison lines join the
  yearly points.
- **Charts:** below the player's charts, *You and the rivals* compares development,
  regiments and monthly income with the current rivals (at most three in EU4); with no
  rivals, with the three strongest great powers.
- **Colours:** lines cross, so every pair of colours must stay apart, not only adjacent
  ones. Checked with the data-viz validator on the panel's surface: only three hues pass
  every pair (blue, orange, aqua; a fourth hue, yellow or violet, came within 5 CVD of
  one of them). The player is always blue; a third rival is a dashed neutral grey line,
  which differs from the three hues in both normal and colour-blind vision and does not
  rely on colour alone.
- **Colours follow the country.** Sorting the rivals by tag would have repainted France
  when Poland was swapped for Bohemia. `rival_slots` walks the snapshots: a country
  that stops being a rival frees its slot, and a new rival takes the first free one,
  so the others keep their colours.
- **For the model:** `get_trends` adds a table of each country's first and latest
  value of the three numbers.

The user's journal was backfilled again (20 saves, about 2.5 minutes) to carry the
others' numbers: rivals France, Poland and the Ottomans; from 1455 to 1525 Austria's
income went from 16 to 59 a month, France's from 26 to 94, the Ottomans' from 28 to 99.
With the wider set, all three rivals have numbers on all 21 saves.

## D-049 — Comparing with any country the player picks

**Date:** 2026-11-17 · **Status:** Accepted (extends D-048)

Rivals are one comparison; "how am I doing against Castile?" is another. The Charts tab
now has a *Compare with* row above the comparison charts: the countries picked, each
removable, or "your rivals" by default; a list to add one (up to three, the colours that
pass every pair, D-048); and a way back to the rivals.

- **Saved per campaign** in the player's context (`CampaignRecord.compare`, via
  `PanelApi.set_compare`), so the choice survives sessions; the picked countries keep
  their colours in the order picked.
- **Tracked in full:** a picked country joins the countries every snapshot records with
  all six numbers (`take_snapshot(extra=...)`). The list offers the countries that have
  a recorded history: rivals, great powers, neighbours and the 30 largest (61 on the
  user's journal).
- **For the model:** `get_trends` takes up to three `countries` (names or tags) for a
  one-off comparison, without changing what the panel shows.
- **A country that forms another keeps its history.** In 1525 the user's journal had
  Castile until it formed Spain; the save records `previous_country_tags = CAS` on
  Spain, so a comparison looks a country's numbers up under each tag it has had. Spain
  now has numbers on all 21 saves (318 development as Castile in 1455, 759 in 1525).

## D-050 — A war in progress, in detail

**Date:** 2026-11-18 · **Status:** Accepted

Asked about a war against Ragusa and the Ottomans, Claude Desktop said it began on
1532.1.1, the day of the save, and that it could not see occupations or the war score.
The briefing printed the war's `action` field as its start; on the user's save that
field held the save's own date for a war declared in 1528.

- **The start is the first `history` entry** (`war_start`), used by the briefing and by
  the journal ("War began: … (declared 1528.9.17)"). SAVE_FORMAT now says `action` is
  not the start.
- **`get_wars`** (`context.wars`) reads each war: both sides, the war goal and who
  controls it, every province one side owns and the other controls (by owner, with
  development), each side's losses in battle, to attrition and in ships, participation,
  and `last_warscore_quarter`, the war score the game records at its quarterly check.
  The briefing adds one *State* line per war pointing to it.
- **Losses come from the participants, not the battles.** Each participant has 21 loss
  numbers (seven unit types × battle, attrition, captured) that are complete; the
  battles in `history` are not (19 on the user's war, none of Austria's land battles),
  so they are shown as examples, never as a tally.
- **Controllers** are a regex scan like the owners (`Campaign.province_controllers`,
  0.24 s on a 40 MB save).
- **Not covered:** the live war score against each enemy is not in the save; the probe
  mod (D-044) is the way to it. On the user's save: 68 provinces occupied (637
  development), none lost, 100,447 men lost against 54,479, quarterly score 56.

## D-051 — Casus belli in the war check and the targets, from the probe mod

**Date:** 2026-11-20 · **Status:** Accepted (builds on D-044)

The probe mod's casus belli matched the diplomacy screen in three game sessions (D-044),
so the planning tools now use them instead of saying casus belli are unknown.

- **Reading** (`live.casus_belli`): the latest month's check in `logs/game.log`, the
  player's and each subject's (an overlord can declare with a subject's casus belli).
  It is only trusted when the log's heartbeat names the save's country and its date is
  within a year of the save's: the log restarts empty with each game start, and the
  player may have loaded another campaign since. Otherwise the tools say why there is
  none (no log, mod not enabled or no month passed yet, another country, too old).
- **Where it shows.** `check_war`, when the player attacks: a *Casus belli* line under
  the title, with each type's name in the game's language and whose it is ("Humillar a
  su rival (yours); Conquista (Hungría)"). `get_expansion_targets`: a *Casus belli*
  column and a detail line per owner; `?` when the mod did not check that country.
  The CLI's `war-check` and `targets` do the same. `Toolbox` takes the log's path.
- **Wider check.** On the user's 1535 save most targets showed `?`: missions and the
  formable Germany point at German minors that are neither neighbours, rivals nor
  holders of claims. The mod now also checks every country on the player's continent
  (`same_continent = ROOT`, as the game's own events use it). Subjects keep the
  narrower set (neighbours of the player or the subject, rivals, claims and cores) to
  keep the monthly cost down.
- **Prompts:** both now say casus belli are known when the probe mod runs, and that
  `check_war` and `get_expansion_targets` say so when they are not.

On the user's save (log of 1535.04.26): against Poland, "Humillar a su rival (yours);
Conquista (Hungría)"; against Liège, "Conquista (yours)"; Savoy, checked, none. With the
wider check in game (1535.05 to 1535.07): 88 countries checked, 21 with casus belli,
and none of the 15 war targets listed is unchecked any more (the Teutonic Order and
Lübeck: none, as on the diplomacy screen; Denmark: Imperial ban and Imperial campaign).

## D-052 — Income and expenses by category, from the ledger

**Date:** 2026-11-20 · **Status:** Accepted (D-051 is in PR #50)

The briefing gave last month's income and expenses as two totals, so "why am I losing
money?" or "what can I cut?" had no answer from the save. The ledger in the save has
per-category arrays (19 income slots, 38 expense slots) without names.

- **The mapping** comes from the open-source `eu4save` crate (rakaly/jomini, MIT, the
  parser behind PDX Tools), where `income_ledger_breakdown` and
  `expense_ledger_breakdown` name each index; SAVE_FORMAT lists it. It was checked on
  the user's 1535.8.2 save: the categories sum to `lastmonthincome` (81.98) and
  `lastmonthexpense` (63.69), and the large ones sit where the game should put them
  (army maintenance 35.1, fort maintenance 11.4, advisors 10.5; 10.4 of war reparations
  from the peace with Ragusa and the Ottomans). Unnamed slots are summed as "Other".
- **`get_budget`** (`context.ledger`): income and expenses by category for last month,
  this year so far and the previous year, the recurring balance (the game's own
  `last_months_recurring_*`), one-off spending marked, and the largest spending since
  the campaign began (`totalexpensetable`: 45,318 ducats, 43% on the army). War
  reparations come with a note that they stop (10 years, the wiki's Economy page).
- **Briefing:** the economy section adds a *By category* line with the four largest
  sources and costs, pointing to `get_budget`; both prompts point to it for income
  and expenses.

Checked in game (2026-11-20): last month's twelve categories matched the game's own
ledger for July 1535. The campaign's 1,724 ducats on support loyalists also fit: the user
paid them to Bohemia, a junior partner in a personal union, to lower its liberty desire
before integrating it.

## D-053 — The budget over time in the charts

**Date:** 2026-11-20 · **Status:** Accepted (builds on D-052, D-045)

With the ledger mapped (D-052), "why did my balance fall since 1530?" needs the
categories over time, not just this month's.

- **Journal:** each snapshot keeps last month's income and expenses by category
  (`budget`, a few dozen numbers) and, like the numbers, keeps it when old snapshots
  are trimmed. Saves recorded before this have no budget: `chancellor journal
  --backfill` reads them again and replaces their snapshots. On the user's journal it
  filled 31 of 35; the other four came from autosaves the game has since overwritten,
  so the budget lines join their points across those gaps.
- **Charts tab:** a *Where the money comes from and goes* section with three charts:
  income by source, recurring expenses, and one-off spending (buildings, raising
  armies, institutions...). Each budget chart names its three largest categories over
  the whole span in the three validated hues and folds the rest into a dashed grey
  "Other" (D-048's palette: no fourth hue passes every pair), so a category keeps its
  colour on every date. One measure per chart, all in ducats a month; the table view
  gains the same columns.
- **`get_trends`** adds a table of each category's first and latest value.

Checked with the user's 31 saves (1455–1535) backfilled into a temporary journal:
taxation grew from 8.4 to 25.0 a month, production from 2.9 to 16.4 and gold from 2.7
to 12.9; army maintenance from 9.0 to 35.1, peaking near 50 during the war of
1528–1532; the one-off chart shows the two institutions embraced (301 and 476 ducats).
In 1535 "Other" is the largest income line (trade 13.8, war reparations 10.4,
vassals 3.5 together), a cost of the three-hue limit; `get_budget` names them.

## D-054 — Which missions can be completed now

**Date:** 2026-11-20 · **Status:** Accepted (D-051 is in PR #50)

The mission tree said which missions were available (prerequisites done) and listed
their requirements, but not whether the country already meets them: "what can I claim
now?" needed the player to open each mission in the game.

- **Checked against the save:** with the game rules, each available mission's trigger
  goes through the decisions' three-valued evaluator, one requirement at a time:
  `[x]` met, `[ ]` not met, `[?]` could not be checked. The tree opens with a summary:
  which missions can be completed now, which are one requirement away, and which are
  possible but have unchecked parts. `get_missions` and `chancellor missions` both do
  it; the targets report, which only needs the provinces, does not.
- **Two evaluator bugs found on the way**, which also affected the decisions and
  formable nations:
  - A geography scope without `type` (`europe = { owned_by = TUR }`) was read as "all
    its provinces"; the game reads it as "any" (its own files write `type = all` 2,727
    times and `type = any` 18). "El azote de Europa", which asks that the Ottomans own
    nothing in Europe, looked complete because the Ottomans do not own *all* of it.
  - Inside an `OR`, each `if`, `else_if` and `else` was evaluated on its own, and an
    `else_if` whose `if` had applied counted as true, so any `OR` holding one was true.
    "Relaciones ibéricas" (`OR = { if = { limit = { exists = SPA } ... } else_if =
    { limit = { exists = CAS } ... } ... }`) looked complete. An `if` chain is now one
    alternative, as `explain` already treated it at the top level.

On the user's 1535.8.2 save: 18 available missions; can be completed now: Ducado de
Milán, Conseguir Croacia, Sobrepasar a los polacos; one requirement away: nine (among
them Imperio multicultural, adm tech 10 with 9 now, and El azote de Europa); possible
with unchecked parts: five (Relaciones ibéricas needs development double Spain's, a
variable comparison the evaluator does not do). In game, the three it called
completable could be completed.

## D-055 — Alerts for missions and nations ready to claim

**Date:** 2026-11-20 · **Status:** Accepted (builds on D-054)

With missions checked against the save (D-054), the panel can say what is ready
without the player asking.

- **What counts as ready** (`alerts.ready_now`): available missions whose requirements
  are all certainly met, and formable-nation decisions that can be taken. A requirement
  the evaluator cannot check keeps a mission out, so the alert never claims too much.
  About 3 seconds on the user's save, computed once per save by the `Toolbox`
  (`Toolbox.ready()`), only with the game files.
- **Panel:** an `info` alert lists the missions that can be completed, and a `medium`
  one the nations that can be formed, as long as they are ready.
- **Journal:** each snapshot of a save read keeps what was ready (`ready`, the mission
  and decision keys), and the changes between two saves say what became ready
  ("Mission ready: …", "Can now be taken: …"), so "since your last save" and
  `get_campaign_journal` mention it once. Backfilled saves skip the 3 seconds and keep
  no `ready`, so no line is made against them.

On the user's 1535.8.2 save the panel gains "3 missions can be completed: Ducado de
Milán, Conseguir Croacia, Sobrepasar a los polacos", next to the coalition and
overextension alerts. The journal's lines start from the next save read, the first
with `ready` recorded.

## D-056 — Advise: structured recommendations from rules over the save

**Date:** 2026-11-20 · **Status:** Accepted (first rung of "Claude plays", VISION)

The vision's last ladder is Advise, Guide, Act. Each tool so far describes one side of
the campaign, and the model put them together itself, unevenly. `get_recommendations`
turns what the code already computes into a ranked list of actions.

- **Structured, not prose** (`context.advice.Recommendation`): a `kind`
  (`complete_mission`, `form_nation`, `fix_deficit`, `repay_loan`, `plan_income`,
  `buy_technology`, `spend_power`, `save_power`, `buy_idea`, `raise_stability`,
  `core_province`, `declare_war`, `get_casus_belli`, `hold_expansion`,
  `work_towards_mission`), a target, a priority (`now`, `soon`, `consider`), the facts
  behind it and the tool with the details. A stable kind and target are what "Guide"
  will map to the game's screens and "Act" will carry out.
- **Rules, not guesses:** each comes from numbers the player can check: missions and
  nations ready to claim (D-055); a recurring deficit, a loan the treasury can repay,
  war reparations that will stop; monarch power near the cap or a technology that is
  affordable and not ahead of its time; overextension with the cheapest cores; the best
  expansion targets (odds 2x or more, no truce or allied defender, coalition risk not
  high), dropping the ones whose only reason is a mission already claimable; 3+
  countries at 50+ AE; missions one requirement away, with the requirement.
- **Goals:** the player's recorded goals head the list, and a recommendation whose
  target country, or a proper name in its mission title, appears in a goal is marked
  with it and comes first within its priority.
- **Choosing is left to the model and the player:** the output says these are options
  to weigh with the goals, not a plan. The prompts point to the tool for "what next?".
- **Casus belli:** the advice takes them as an optional input with the probe mod's
  shape (D-051), so it does not depend on the draft PR #50; until that merges, targets
  say the casus belli were not checked.

On the user's 1535.8.2 save (about 5 seconds): now, the three missions ready; soon,
coring Widin (6% overextension, 35 adm) and letting AE cool down (34 countries at 50+,
Switzerland 101); to consider, the Austrian Netherlands mission (16 provinces in the
region, matching goal #1), the war reparations (13% of income), wars on the Teutonic
Order (5.2x, low risk) and Liège (2.5x, medium risk). Two fixes came from
reading it: a title's first word no longer matches goals ("Liberar los Balcanes" was
tied to "liberar un vasallo"), and a missing requirement is shown whole.

## D-057 — When to claim a mission: rewards that depend on a condition

**Date:** 2026-11-20 · **Status:** Accepted (refines D-054 and D-056)

The first recommendations said "complete «Sobrepasar a los polacos» now" and dropped the
war on Poland. The user pointed out that players often wait: that mission's reward is
a casus belli to restore the union with Poland only if Poland is small enough, and
plain conquest claims otherwise, so they were taking land from Poland first.

- **Reward conditions** (`missions.reward_conditions`): the `if`/`else_if` blocks and
  `complex_dynamic_effect` branches of a mission's effect, following hidden effects and
  the scripted effects it calls (`GameRules.scripted_effects`, now loaded; cache format
  5). A branch that only wraps further branches is not listed: the inner ones decide.
  That matters here: the game's text says "less than 400 development", but the scripted
  effect grants the casus belli only below 300.
- **Only what waiting can change:** conditions without a number the player can move (a
  DLC, the age, the religion) are left out; each one kept shows the current value
  against the threshold. The evaluator gained
  `total_own_and_non_tributary_subject_development` (the country plus its subjects,
  tributaries left out) and `Evaluator.number` for showing values.
- **Missions:** an available mission lists them under "The reward depends on
  conditions (it may pay to claim it later)".
- **Advice:** a mission that can be completed but whose reward improves under an unmet
  condition becomes `time_mission` ("complete now, or wait for the better reward", soon),
  with the value and what would be lost; and the war targets keep a reason a waiting
  mission names, adding that taking land brings that reward closer.

On the user's 1535.8.2 save it is the only such mission: Poland has 303 development and
its junior partner Lithuania 392, so 695 against the 300 needed; the war on Poland
(2.7x, low coalition risk) is back with that reason. The user's plan of shrinking
Poland holds, though it is further off than the game's "400" suggests, and Lithuania
counts too.

## D-058 — An evaluation set of real questions, run against a real save

**Date:** 2026-11-20 · **Status:** Accepted

Several bugs this week were found by hand on the user's save: a region scope read as
"all provinces", an `else_if` that made every `OR` true, the Poland reward's real
threshold (300, not the 400 the game shows). The unit tests use small fixtures, which
had not caught them. Before building "Guide" on the recommendations, the answers to
real questions get a safety net.

- **Cases** (`evals/*.toml`, read with the standard library's `tomllib`): a question,
  the tool the model should call for it, its input, and checks on the output: text it
  must contain, text it must not, regular expressions it must match; `why` says where
  the expected facts come from (the game screen, a fixed bug). Checks use keys, tags and
  numbers (`hab_milan`, `(POL)`, `695`), not localised names, so they hold in any
  language and the committed files stay in English; recommendations now show their
  target key beside their kind (`[time_mission hab_surpass_poland]`).
- **Tied to one save:** saves are never committed, so a set names a save in the
  player's folder (`Austria1535_08_02.eu4`, 1535.8.2) and runs where it exists:
  `chancellor eval` reports each case and exits 1 on a failure, and `pytest` runs each
  set as one test (about 8 seconds, with the real game-data cache) and skips it
  elsewhere, as in CI. The tools get an empty player context, so the answers depend on
  the save alone.
- **The first set** has 15 cases: the three missions the user confirmed can be
  completed; the Ottoman and Iberian missions (the two evaluator bugs); the
  multicultural mission (administrative technology 9 of 10); the Poland reward (695
  against less than 300); the budget the user matched with the ledger; the war
  reparations ending; Austria-Hungary one requirement short; at peace; who defends
  Poland (Lithuania); the targets and the Ottoman truce; the briefing's basics; trade at
  Venice; and the recommendations (missions to complete, Poland's to time, the war on
  Poland bringing it closer).
- **It catches what it should:** with the region bug put back, exactly the Ottoman case
  failed.

A set is a baseline for a save that does not change: when a tool's wording changes on
purpose, the set is updated with it.

**Any country, not just the one played.** The user asked that every tool work whatever
the country, Austria or Japan. On the same save, every tool was run as if each of 26
countries were the player (France, the Ottomans, the Papal States, Ming, Ashikaga,
Spain, Portugal, Great Britain, Russia, Crimea, the Nogai, Vijayanagar, Ethiopia,
Hungary, the Iroquois, the Aztecs, Korea, Delhi, the Mamluks, Switzerland, three
colonial nations, Ulm, Kilwa): none failed, each got its own mission tree, budget,
targets and recommendations. Two fixes came of it: a colonial nation's empty mission
slot was listed as a missing series named "{}"; and `get_recommendations` for a
country other than the player's did not compute the missions it can claim. The source
names Austria only in comments recording where numbers were checked against the game.
Tests keep it so: the tools answer as Turkey, Bohemia and Hungary on the small fixture
save (everywhere), and every tool answers as Ashikaga, the Iroquois, a colonial nation
and Ming on the real save (where it exists). A gap remains, not an error: the briefing
has a section for the Holy Roman Empire but none for China's Mandate of Heaven or
Japan's shogunate (closed by D-060).

## D-059 — Guide: each recommendation as steps in the game's interface

**Date:** 2026-11-20 · **Status:** Accepted (second rung of "Claude plays", VISION)

Recommendations carry a stable kind and target (D-056, D-058); Guide turns them into
the clicks that carry them out, so the player (and later "Act") knows where each action
lives.

- **Names from the game, in its language** (`context.guide`): every screen and button is
  named with its localisation key, read from the game's files, so the steps say
  «Misiones», «Crear un núcleo», «Declarar la guerra» in the user's Spanish game and the
  English names in an English one; an English fallback covers a missing key. The tabs'
  keys are the `HEADER_*` ones the country screen uses (Decisions is
  `HEADER_MISSION_REMOVE`); the buttons' keys are those of the province and diplomacy
  windows (`CV_BUILD_CORE`, `WARTITLE`, `FABRICATE_CLAIM`, `CV_REPAY_LOAN`,
  `CV_BOOST_STABILITY`, ...).
- **Only what the files settle:** F1 opens the country screen (`interface/topbar.gui`);
  the other tabs' function keys are in the game's code, not its files, so steps go
  through F1 and the tab rather than guess a key.
- **Per kind:** missions (the Missions tab; for a mission worth timing, "or leave it"),
  formable decisions, a technology (the button under its column), an idea, stability,
  coring (the province by the name the map shows: the save's, so Widin, not the
  localisation's Vidin), a loan, a deficit (maintenance sliders, an advisor to
  dismiss), a war (a province of the target, its flag, its diplomacy, Declare War), a
  claim to fabricate, relations to improve. Kinds that are not one action (planning for
  the end of the war reparations) get no steps.
- **Where it shows:** a *How* line under each recommendation in `get_recommendations`;
  the evaluation set checks it.

## D-060 — The Empire of China and the shogunate in the briefing

**Date:** 2026-11-20 · **Status:** Accepted (closes the gap noted in D-058)

Running the tools as other players (D-058) showed the briefing had a section for the
Holy Roman Empire and nothing equivalent for East Asia's two systems.

- **Empire of China** (`Campaign.celestial_empire`, from the save's `celestial_empire`
  block): shown to the emperor and to its tributaries (subject type `tributary_state`;
  a vassal of the emperor is not one). Role, emperor, the Mandate
  (`imperial_influence`, of 100), the celestial reforms passed (their `_title`
  localisation), the decree in force with the date issued (the decree's own key names
  it), and, for the emperor, how many tributaries.
- **Japan:** shown to the shogun (the country with the `shogunate` government reform)
  and its daimyos (subject type `daimyo_vassal`): role, the daimyos, and the Shinto
  isolationism level when the save has one.

On the user's 1535 save: Ming as emperor with Mandate 84.2, three reforms (Gaituguiliu,
the sea ban, administrative divisions), the decree "Proclamado nombre dinástico" of
1532.7.3 and seven tributaries; the Khalkha as a tributary; Ashikaga as shogun with
Uesugi as its daimyo. Japanese countries outside the shogunate (Oda here) get no section
yet: the save does not mark them as such.

## D-061 — Goal progress: a recorded goal tied to measures from each save

**Date:** 2026-11-20 · **Status:** Accepted (the part left of the goals and watches idea)

The player's goals are recorded in their own words (D-039), so nothing said how far
along they were. A goal now carries measures, chosen by the model from a closed list,
the way a watch carries conditions (D-041), and each save reads them.

- **Measures** (`player.goals`): `mission` (completed, can be completed, requirements
  met, locked), `formable` (a decision's requirements met), `provinces` (held in an
  area, region or superregion, with the non-tributary subjects or not, against a count
  or the whole), `country` (another country becoming the player's subject, or gone),
  and `metric` (any watch condition: development, income, war odds against a
  country...). Countries are stored as tags, so a country that is gone is still named.
- **`track_goal`** attaches measures to a goal, replacing earlier ones; countries are
  resolved and mission, decision and geography keys are checked against the game
  files, with an error that names the key to use. Recording a goal now answers "measure
  it with track_goal", and both prompts say to.
- **Where progress shows:** under each goal in `get_player_context` ("2 of 3 reached:
  ...", or "not measured yet") and in the panel's *Your plan*, on its own line. The
  mission tree and the decisions are computed once per save (about 3 seconds) and only
  when a goal uses them.

Tried on a copy of the user's context, with their two goals: Gelre still exists, the
Austrian Netherlands mission lacks its requirement, the Low Countries at 8 of 16
provinces (Holland, a vassal, counts); Naples not yet a subject, the Naples mission at 0
of 2 requirements, war odds against France 1.88 (reached, 1.5 wanted).

## D-062 — Other models: LM Studio as an MCP client, and measuring a local model

**Date:** 2026-11-20 · **Status:** Accepted; the measurement is pending

The idea of 2026-11-16 (ROADMAP): the tools should not need a paid Claude plan. Its cheap
step is another MCP client running a free local model.

- **The model:** Qwen3 4B Instruct 2507, Q4_K_M (2.5 GB), in LM Studio. The user's laptop
  has 8 GB of RAM and an integrated graphics card, so only a small model fits; Qwen3 is
  among the small families that call tools well (Llama 3.2 3B worse, Gemma 3 without
  native tool calling). LM Studio runs the model and is an MCP client itself.
- **Configuration:** LM Studio reads the same `mcpServers` shape as Claude Desktop from
  `~/.lmstudio/mcp.json`. `chancellor mcp-config --client lmstudio --write` adds the
  Chancellor there, keeping other servers and copying the old file to `mcp.json.bak`.
- **Measuring:** `chancellor eval --model <id>` asks the evaluation questions to a model
  behind an OpenAI-compatible API (`llm.local`: LM Studio's `localhost:1234/v1`, Ollama
  and others), runs the tools it calls, and reports per case whether it called the
  expected tool, whether its answer has the case's `answer` facts (numbers, so any
  language works), the time, and whether a tool result was cut to fit its context.
  Results print as they come, so a slow run can be stopped without losing them. This
  is a measuring loop, not a second chat: the panel's chat stays on Anthropic (D-028).
- **A fix for small models:** Qwen passed `country: "player"` instead of leaving it out,
  and the tools answered "no country named 'player'"; words such as player, me or my
  country now mean the player (`PLAYER_WORDS`).

What was measured on the user's laptop: 16k of context did not fit beside the model
(12k did, CPU only); the tool descriptions take about 5k tokens, cached by LM Studio;
reading a tool result runs at about 12 tokens a second, so a 4,000-token result costs
5–6 minutes, and a question 5–15 minutes. In the questions it got through, Qwen chose
the expected tool (trade, missions, budget). A first run of six questions was stopped
at the third: LM Studio was also serving other requests, and the replies had no length
cap (now 1,024 tokens). **Pending:** a full run with LM Studio otherwise idle (about an
hour), to say how many answers are complete.

## D-044 (follow-up) — The war score read at war, 2026-11-21

The probe's third question, answered in the user's war against Poland (with Lithuania,
Gotland and Naples on Poland's side), played from 1537.08 to 1537.11 with the mod on:

| | Game's screen (1537.12.17) | Mod, direct (`trigger_value:war_score`) | Mod, ladder | Save, `last_warscore_quarter` |
| --- | --- | --- | --- | --- |
| Poland (war leader) | +87 | 61, 74, 78, 88 (Aug–Nov) | 60, 70, 75, 85 | 87 |
| Lithuania | +84 | — | -100 | — |
| Gotland | +0 | — | -100 | — |

- **The direct value works** and is exact (to three decimals): it is the war score
  against the enemy war leader, the one the game shows for the whole war and that
  decides a peace with the leader's side. The ladder agrees with it, rounded down to 5.
- **Per ally it cannot be read:** `war_score_against` holds for none of the ladder's
  steps against Lithuania or Gotland (-100), though the game shows +84 and +0; the
  trigger only answers for the war leader.
- **The save's quarterly score is the same number** (87 here; 56 in the Ragusa war of
  D-050 was not checked in game then): `get_wars` already reports it, a quarter late at
  most; the mod gives it monthly.

Next: the live score into `get_wars`, the war check and the recommendations ("+88
against Poland: enough to ask for peace"), from the mod's log when it runs, else the
quarterly score.

## D-063 — The live war score and the casus belli in the advice

**Date:** 2026-11-21 · **Status:** Accepted (closes PR #50: D-044, D-051)

With the war score checked against the game (D-044 follow-up), the probe mod's two
readings go where they are useful.

- **Reading** (`live.war_score`): the latest month's `direct` value and `ladder` (the log
  reader now keeps only the latest month of them, as of the casus belli), trusted like
  the casus belli when the log is the save's country's and within a year. The exact
  `direct` value is used when the player is in one war (it does not say which war);
  otherwise the ladder's value against that war's enemy leader, to the nearest 5 below.
  Against a leader's ally nothing can be read (-100), so nothing is said.
- **`get_wars`:** "War score: +88 against Polonia (exact, the probe mod on 1537.11.22)"
  above the quarterly one; without the mod, the quarterly score says where the live one
  is. "1 province" is now singular.
- **Peace in the recommendations** (`make_peace`): a war score of +50 or more against
  the enemy leader is "ask for peace" (now from +90, otherwise soon), with the score and
  its source, the provinces occupied, and a note that a separate peace with an ally has
  its own score; -50 or less is "seek a peace" (now). Guide's steps: a province of the
  leader, its flag, its diplomacy, «Pedir la paz» (`PEACETITLE`).
- **Casus belli in the recommendations:** the probe mod's check (D-051) now feeds the
  war targets, so "War on Lieja: casus belli Conquista" or "get a casus belli" replace
  "not checked"; without it, the reason the lookup gives says why.
- **Prompts and `get_wars`' description** say the score is against the enemy leader,
  monthly with the mod, quarterly without.

On the user's 1537.12.17 save, with the game just restarted (no month in the new log
yet): "Ask Polonia for peace", war score +87 at the quarterly check, 59 provinces
occupied (581 development). With the previous session's log, the live +88.

## D-064 — Peace terms: what each demand costs, from the game's peace screen

**Date:** 2026-11-21 · **Status:** Accepted

Asked whether to fight on to 100% or ask Poland for peace now, Claude Desktop proposed a
deal that released Lithuania, Poland's junior partner, "cheaply (about 0.4 times its
provinces, per the wiki)". On the peace screen it cost 100%: the wiki leaves out the cap.
Nothing in the tools priced a peace, so the model took the wiki's 1.24 rules.

- **The rules, measured, not assumed.** The user read the peace screen for eighteen
  Polish and Lithuanian provinces: every one costs exactly 0.8 × its development (Barlad
  5 → 4.0, Poznan 25 → 20.0, Varsovia 22 → 17.6, Vilnius 24 → 19.2, Viazma not occupied
  8 → 6.4). The wiki's 1.24 formula (5 per province, the capital, trade power, buildings,
  the size of the owner) does not apply in 1.37: Vilnius has a capital, a centre of trade
  and three buildings and still costs 0.8 × 24. Releasing a subject costs 0.4 × its
  provinces' cost, capped at `MAX_PEACE_COST_CANCEL_SUBJECT` = 100 (Lithuania, 393
  development: 126, so 100). Fixed treaties come from `common/defines.lua`.
- **The other columns** of the peace screen: the last is the prestige (0.25 per
  development), the one before the aggressive expansion (about 1.33 per development for
  Poland, 2 for its ally; none for Barlad and Besarabia, claims of Austria's vassal
  Hungary). So a claim or core of the player **or of its subjects** marks a demand as
  justified.
- **`get_peace_options`** (`context.peace`): for each of the player's wars, the war score
  to spend (live from the probe mod, else the quarterly check, D-063), each enemy's
  development with and without its subjects (what a mission such as "Sobrepasar a los
  polacos" measures), the subjects that can be released with their cost and whether it
  fits, every enemy province that is occupied, claimed or the war goal with its cost,
  whether it is occupied and whose claim it is, and the fixed treaties. The prompts send
  the model there before it advises a peace; `get_wars` and the peace recommendation
  point to it.

Not covered: modifiers the user's game did not show (great projects, autonomy, ideas that
lower war score costs), the AE a deal adds (the war check estimates a conquest's), and
the score of a separate peace with one of the leader's allies, which only the peace
screen shows.

## D-065 — A steering merchant's direction is the save's `steer_power` index

**Date:** 2026-11-23 · **Status:** Accepted

`get_trade` said which nodes feed the home node but not where a steering merchant pushes,
so a merchant steering the wrong way could not be spotted. The direction is in the save
after all: a country's block in a node has `steer_power=N`, the index of the outgoing
link it steers along, in the order of `common/tradenodes` (absent: the first link).
Evidence on the 1539 save: every value is below the node's number of links; the node's
own `steer_power` list splits the steering power by link in that same order; and of 422
steering merchants in the world, 10 push away from their home node, about what the AI
would do. Austria's merchant in Wien has no index, so it steers to Venice, where it
collects.

The report shows `steering → Venecia` and lists merchants steering away from home. Not
checked against the game's trade screen yet: compare one merchant's arrow there.

## D-066 — More conditions from the save, and scripted titles

**Date:** 2026-11-23 · **Status:** Accepted

A measurement on the 1539 save found 58% of major and 62% of other decision requirements
unknown, and 41 of 83 mission requirements. Most came from conditions whose answer is in
the save: estate loyalty (`estate.loyalty`), crown land (100 minus the estates'
`territory`), the ruler's skills and heir (history records), advisors and their skill
(province history), idea groups (`active_idea_groups`, 7 = full), great power rank, HRE
reforms, electors, imperial authority and size, opinion (`active_relations.cached_sum`),
years of income, cavalry (`total_count`), rebel-held provinces, monarch power, deficit,
states (`map_area_data`), the owner's religion, buildings, `always`, and the
`any_`/`all_` scopes over subjects, allies, neighbours, rivals and countries. A built-in
government attribute (`heir = yes` at the top of `monarchy_mechanic`) was read as absent,
so `has_government_attribute = heir` was false for every monarchy; it now counts.

Left unknown on purpose: estate influence (base, privileges, land share, modifiers and
scripted conditions; computing it without checking against the game would guess; the
probe mod could log it with an `estate_influence` ladder), `army_size` (the unit is not
certain), revolutions, disasters, wars won.

Titles written as `[Root.GetActsOfUnionDecisionTitle]` name a `defined_text` in
`customizable_localization`: a list of localisation keys, each with a trigger. They are
loaded with the localisation and resolved by the condition evaluator, with the ruler's
dynasty and the country's name filled in ("Extiende los von Habsburgs", "Gloria a von
Habsburg!"). Without an evaluator only the choices that do not depend on the country are
resolved. 564 of 565 scripted decision and mission titles resolve for Austria.

## D-067 — PDX Tools: link to it, do not embed or reuse it

**Date:** 2026-11-23 · **Status:** Accepted

The vision named PDX Tools (pdx.tools) as the reference for save analysis and asked
whether to link it, embed it in a tab, or reuse its parsing libraries. What it is
(its README and site, 2026-11-23): an AGPL-3.0 web app that parses a save in the browser
(WASM) and uploads it only when the player chooses to share it, for EU4 1.29 onwards
(a 1.37 asset bundle exists), with a map, budget and mana graphs, the ledger, insights
and timelapses. A save is opened only by the file picker or a drop: no URL parameter,
no documented API, no embedding support.

- **Not embedded.** A tab with the site would need the internet, a drop the panel cannot
  make for the player, and a narrow window the site is not built for.
- **Not reused.** Its parser is Rust; linking AGPL code into this project would put the
  whole project under the AGPL, and our Python parser already reads what the tools need
  (the ledger indices were taken from the `eu4save` crate's mapping, D-052, as facts,
  not code).
- **Linked.** *Open in PDX Tools* in the panel's menu opens the site in the browser and
  shows the newest save selected in Explorer, ready to drop. The two complement each
  other: PDX Tools has the map and one save in depth; the Chancellor has the campaign
  across saves, the player's goals and the chat.

## D-068 — The model points the player to a chart

**Date:** 2026-11-23 · **Status:** Accepted

`get_trends` gave the model the numbers, but the player saw them as a table in the chat
while the same trend was drawn in the panel. The model now names a chart and the panel
shows it.

- **`show_chart`** (MCP and the API chat): one of twelve charts by id (the six of the
  player's numbers, the three budget charts, the three comparisons; `countries` sets the
  comparison, kept in the panel as if the player picked it, D-049). It writes
  `chart_request.json` beside the player's context and returns the chart's numbers (up
  to twelve dates and its events) with a line telling the model to name the chart.
- **The panel** checks the file every second; a request newer than the panel's start
  brings it up (the overlay opens on one screen, the window shows on two), opens the
  Charts tab, scrolls to the chart and marks it for four seconds. A file is the channel
  because Claude Desktop runs the MCP server in another process.
- **One list of ids**: `player.charts.CHARTS` and the ids in `charts.js`; a test keeps
  them equal.

Not covered: Claude Desktop cannot draw the chart inside the chat; the panel is where
the player sees it.

## D-069 — Act: Claude Desktop clicks, the Chancellor checks before and after

**Date:** 2026-11-23 · **Status:** Accepted (third rung of "Claude plays", VISION)

The last rung is acting in the game. The user chose the free path: Claude Desktop's own
computer use does the screenshots and clicks, so nothing is billed to the API (5 EUR
budget), and the Chancellor adds what screenshots cannot.

- **`prepare_action(kind, target)`** (`context.act`), for the recommendation kinds that
  are one click sequence and that the save can confirm: `complete_mission`,
  `form_nation`, `buy_technology`, `buy_idea`, `raise_stability`, `repay_loan`,
  `core_province`, `declare_war`. It checks the action against the save (the mission is
  open and its requirements met, points or ducats enough at the computed cost, the
  province not a core, no truce or war already), and when anything fails it says so and
  records nothing. Otherwise it returns numbered steps from Guide (D-059) in the game's
  own words, preceded by pausing the game, with the last step (the one that spends,
  claims or declares) marked CONFIRM, and the rules: act only on the player's request
  and one action at a time; a screenshot before each click; stay inside the game's
  window; stop and describe when the screen differs; ask the player to save afterwards.
  The action and the values to compare are kept in `actions.json` beside the player's
  context (the last 20).
- **`verify_action(id)`** reads the newest save: not later than the one prepared against
  means "save first"; otherwise the mission is in `completed_missions`, the technology
  level or idea count or stability went up, a loan went, a war with the target exists,
  the player's tag is the formed nation's; coring takes months, so a core or the adm
  power spent (90% of the cost) counts as started.
- **Administrator rights:** the user runs EU4 as administrator, and Windows drops
  synthetic input from a process with lower rights (UIPI). Claude Desktop must run with
  the same rights, or EU4 without them; the rules tell the model to say so when clicks
  have no effect.
- **The prompts** tell the model to call `prepare_action` before acting and
  `verify_action` after the player saves; the API chat gets the same lines but has no
  computer use, so it only prepares.

On the 1539 save every kind tried was correctly ruled out: a technology at 478 points with
293, stability already +3, a truce with Naples, no loans. Not yet run live: it needs a
game session with Claude Desktop's computer use.
