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
- [x] Advisors and generals in the briefing (with the monarch power section, D-029)

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
- [x] `app.ui`: pywebview panel with the header (country, date, save) and key numbers
  (`chancellor app`, optional `ui` extra)
- [x] `watcher`: background save watching with live refresh of the panel; a save is
  reported once it has stopped changing (the terminal chat still checks before each
  question)
- [x] Alerts: wars, coalition and countries at 50+ AE, truces with rivals or neighbours
  ending within two years, losses, loans, overextension, war exhaustion, negative
  stability, monarch power near the cap, an imperial reform ready
- [ ] Alerts: missions or formables that became available since the previous save
- [x] `app.layout`: docked layout on two screens and undock; on one screen a floating,
  draggable icon that opens the panel and Claude Desktop as an overlay (D-022), shown
  only while the game is in front; verified live with EU4 running as administrator; the
  icon is a native, truly round window (D-023)
- [x] Docking: follow a screen appearing or dropping while the app runs, remember the
  icon's place, let the player choose the overlay side, and move the rarely used
  actions into a menu (D-027; docking over Miracast verified 2026-11-14)
- [ ] Docking: dock automatically at start
- [x] Quick questions (copy the prompt and bring Claude Desktop forward) and a
  system-wide hotkey, `Ctrl+Shift+Space` by default (D-026); verified live on two
  screens with EU4 running as administrator. Sending them to the API tab comes with
  that tab
- [x] API chat tab behind the player's chat-mode switch (D-020), on a budget (D-028):
  priced responses, a cap per question, a running total across sessions, Sonnet 5.5
- [ ] Evaluation set of real questions with expected reasoning
- [ ] Answer quality of the chat. First live question (2026-11-14, Sonnet 5.5 at
  `medium`, $0.031): "how is my campaign going?" used only the briefing and the world
  overview; the facts were right and the diagnosis pointed the right way (AE near a
  coalition), but the advice was generic or wrong for the game: spend ~390 military
  points on military technology (not enough) or on generals (Austria has enough), "only
  declare war with a casus belli" (always true). Needs game knowledge in the prompt or
  the tools (technology costs, what points are worth), more tools per question, or a
  higher effort; measure it with the evaluation set above
  - [x] Game mechanics computed in the tools (D-029): the briefing says what monarch
    power buys (technology costs with their parts, matching the game's tooltip exactly
    for Austria in 1483; ideas, stability, generals), the monthly gain, the months to
    each technology, leaders and advisors
  - [x] The AE a conquest adds (D-030), in the war check; to be checked against a peace
    deal in game (distance falloff and reach)
  - [x] Development cost per province (D-031), with each province's terrain read from the
    map images; matches the game's tooltips (Vienna 59, Ostmark 53, Tirol 56)
  - [ ] Coring cost: no tooltip yet (the one non-cored province was already being cored);
    calibrate at the next conquest
  - [ ] Technology cost changes from idea bonuses, policies, reforms and estate
    privileges
  - [x] Strategy knowledge: the wiki as a searchable source (`search_wiki`, D-032), from
    the player's own `Special:Export` files; to be judged with the play-test questions
  - [ ] Player feedback on answers (thumbs up or down with a note) to find bad advice

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

### Play-test findings (2026-11-14, Austria 1483 save, through the MCP tools)

The first round of fixes held up: the briefing now covers the HRE, aggressive expansion,
overextension and monarch power, and truces and allied defenders are filtered. New
findings, most harmful first:

- [x] War check and targets: coalition risk. With the coalition dissolved, Venice
  (AE 74), Switzerland (83) and Milan (82) ranked as easy targets although 34 countries
  hold 50+ AE; both now show the owner's AE and its neighbours at or near the
  coalition threshold, and high-risk targets rank last among unblocked ones (D-024)
- [x] Estimate the AE a conquest would add (province development, distance, culture,
  religion, HRE), so the risk can say how many provinces are safe to take (D-030)
- [x] Checklists: never truncate an unmet branch. Austria-Hungary's only failing
  requirement (an `if`/`else` on administrative technology, 20 here) printed as an
  empty "Otherwise:" and "…"
- [x] Checklists: name the owner when `mission_completed` refers to another country's
  mission. `hun_a_multicultural_empire` read as "Imperio multicultural", the same title
  as Austria's own `hab_multicultural_empire`
- [x] War check: ally reliability. Castile counted as "likely" with an opinion of +4;
  allies with an opinion below 25 or trust below 30 are now "possible" (D-025)
- [x] Targets: name the countries behind "up to N" (Ragusa's possible defender is the
  Ottomans)
- [x] Decisions: formables marked "may apply" that are out of reach. Great Britain
  showed because `has_government_attribute` was not checkable; the evaluator now reads
  the attributes from `common/government_reforms`. The Byzantine Empire is genuinely
  visible to Austria and stays
- [x] Small: subject roles mix English and localised names; national ideas shown as
  "0/7" like an idea group; average unrest not rounded

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

### Idea: goal-based watches and a campaign journal (2026-11-13)

Not scheduled. Raised after using the panel: its key numbers and alerts repeat what the
game already shows, and the game's own alerts are literal (a problem, or something you
can do now) and know nothing of the player's plans. The panel could instead watch for
what *the player* cares about.

- **Watches**, written in plain language in the chat and turned by Claude into a
  structured rule (new MCP tools: `create_watch`, `list_watches`, `delete_watch`),
  checked on every new save, firing once:
  - *thresholds on your country*: "tell me when I have 200 ducats" (a building you are
    waiting for), manpower back above 80%, enough monarch power for a core or an idea;
  - *opportunities against a target*: "tell me when France is weak enough to attack":
    a combination the war check already measures (odds of 1.5x or better, no truce,
    France at war elsewhere or with high war exhaustion, an alliance of hers broken);
  - *changes in the world*: a coalition against you dissolving (members dropping below
    50 AE), a truce with a rival ending, an ally declaring a war, a ruler or heir dying.
- **Goals**: the plan agreed in the chat ("conquer France", "form Austria-Hungary")
  tracked with the checklists the tools already produce (missions, formables, war
  odds), so the panel shows progress towards what the player chose.
- **Campaign journal** (the "logger" idea): a record of notable changes between saves
  (wars, alliances, provinces, rulers) plus fired watches. It gives the panel a
  timeline ("since your last save..."), gives the chat memory of what happened, and is
  the base for Phase 5's history across saves.
- Where alerts show: the panel, a badge on the floating icon (one screen), and
  optionally a Windows notification while the overlay is closed.
- Constraints to design around: watches are only as fresh as the last save (a monthly
  autosave keeps them close to real time); "weak" must become concrete numbers the
  player can see and adjust; watches and the journal persist in a small file in the
  user's data folder; creating them through Claude Desktop costs nothing (D-016), and
  the paid API is never involved unless the player switches it on (D-020).
