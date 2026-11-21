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
- [ ] Map advisors and province internals (ledger category indices: done, D-052)
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
- [x] Income/expense breakdown by category (D-052)
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
- [x] Run from any folder: `chancellor setup` finds the game and the player's folder
  and writes `~/.eu4-chancellor/config.env` (D-047)

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
- [x] Evaluate mission triggers to tell "available" from "completable now" (D-054)
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
- [x] Alerts: missions or formables that became available since the previous save
  (D-055): a panel alert while any is ready, and a journal line when one becomes ready
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
- [x] Evaluation set of real questions with expected answers (D-058): `evals/*.toml`,
  run by `chancellor eval` and by `pytest` where the set's save exists
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
  - [x] The AE a conquest adds (D-030), in the war check; checked against a peace deal
    on 2026-11-15 (D-034): continuous distance falloff, the player's difficulty
  - [ ] AE leftovers from that check: the loser of a province (Cilli: 12.7 estimated,
    about 10 in game) and a distant country (Poland: 5.2, about 4) come out high; Milan
    and Mantua were missing from the game's coalition list for an unknown reason
  - [x] Development cost per province (D-031), with each province's terrain read from the
    map images; matches the game's tooltips (Vienna 59, Ostmark 53, Tirol 56)
  - [x] Coring cost per uncored province (D-033), in the briefing; matches the game's
    tooltips (Friaul 61 in 37 months, Treviso 102); administrative efficiency now
    multiplies after the sum (D-035)
  - [ ] Coring: permanent claims (-25%; the save lists only `claims`, so every claim
    counts as temporary, -10%) and the higher cost of provinces whose core belongs to a
    country with `enemy_core_creation` ideas
  - [ ] Technology cost changes from idea bonuses, policies, reforms and estate
    privileges
  - [x] The player's context kept per campaign (D-039): goals, wants and limits,
    decisions and notes, and what the player says about themselves, read at the start of
    a chat (`get_player_context`) and recorded as the player states them
    (`update_player_context`); `chancellor player-context` shows it
  - [ ] Player context: first try across two Claude Desktop chats (2026-11-16): the
    first chat, where the player set out their plans, recorded nothing; the second read
    the empty context, found the plans in Claude Desktop's earlier chats and recorded
    two faithful goals. The planning tools now end with a line on the context (D-040);
    try again
  - [x] Panel: a "Your plan" section with the player's entries and waiting watches,
    each removable (D-041)
  - [x] Watches (D-041): "tell me when ..." as conditions on 24 metrics read from the
    save (treasury, manpower, monarch power, technology, AE, coalition, war odds, war,
    truce, alliance, year, ...), set with `create_watch`, checked on every save, firing
    once; fired watches lead the panel's alerts and the planning tools' last line
  - [x] Watches tried in Claude Desktop (2026-11-16): "France weak or me strong enough"
    became war odds >= 1.5 with no truce and showed in the panel; the first call
    guessed the condition format, so the MCP schema now types it (D-041)
  - [x] Campaign journal (D-043): a snapshot of the player's country for each save
    read, compared save to save (provinces, cores, wars, allies, subjects, rivals,
    truces, coalition, ruler and heir, ideas, technology, Emperor, imperial reforms,
    key numbers); `get_campaign_journal`, `chancellor journal`, and *Since your last
    save* in the panel; verified in Claude Desktop (2026-11-17)
  - [x] A fired watch is noticed outside the page (D-042): a red dot on the floating
    icon (one screen) and a flashing taskbar button for the docked panel (two screens)
  - [ ] Watches (the dot and the flash were verified live on 2026-11-16): a Windows
    notification only if those prove not enough; more metrics as requests show (an ally declaring war, a ruler or heir
    dying); "or" between conditions if a request needs it
  - [x] Strategy knowledge: the wiki as a searchable source (`search_wiki`, D-032), from
    the player's own `Special:Export` files. Retrieval checked on 2026-11-16 with 12
    queries from the play-tests (D-035): the right section came first for nearly all;
    a long section no longer fills several results
  - [ ] Judge the wiki in real answers: ask play-test questions in Claude Desktop and
    check that it searches, cites and lets the computed numbers win. First try
    (2026-11-16): better answers, but two strategy questions (an expansion plan, idea
    groups) never called `search_wiki`; the tool, the prompts and the strategy tools'
    results now point to it (D-036). Second try, same idea-group question: three
    searches ("Austria strategy idea groups", idea slots, the candidate groups)
  - [x] Briefing: idea slots chosen and free, and the administrative technology that
    unlocks the next with the year its penalty ends (D-037); the model had to recall the
    thresholds or search the wiki for them
  - [ ] Administrative efficiency from absolutism (+0.3% a point, up to 30%) and from
    government reforms, for AE and coring; only technology is counted

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
- [x] Charts tab (D-045): treasury, income and expenses, regiments, manpower,
  development and countries at 50+ AE over the campaign, from the journal's records,
  with its main events marked on the time axis; plain SVG, offline, hover tooltips and
  a table view
- [x] Save history: `chancellor journal --backfill` lists older saves by campaign id
  and reads the groups the player picks into the journal; `get_trends` gives the model
  the same numbers as a table
- [x] You against your rivals (D-048): each snapshot keeps the rivals', great powers',
  neighbours' and the 30 largest countries' numbers (once a year in old snapshots), and
  colours follow the country when a rival changes; the Charts tab
  compares development, regiments and income with the rivals (or the top great powers),
  and `get_trends` adds the same comparison as a table
- [x] Compare with any country the player picks (D-049): a picker in the Charts tab,
  saved per campaign; `get_trends` takes countries too; a country that formed another
  (Castile, then Spain) keeps its history
- [x] Income/expense breakdown by category (D-052): `get_budget` and a briefing line,
  from the ledger's indices as the `eu4save` crate maps them
- [x] Trade (D-046): `get_trade` gives the home node and the share there, merchants
  (collecting or steering), light ships, power and share in every node with whether it
  feeds home, the feeders where the country has no power, and embargoes; the briefing
  points to it. A trade question in Claude Desktop (2026-11-17) had to ask the player;
  asked again with `get_trade`, it answered from the save
- [ ] Trade: which way a steering merchant pushes is not in the save; check whether a
  later save field or the country block records it
- [x] Wars in progress (D-050): `get_wars` gives the real start (the first history
  entry, not `action`), occupations both ways, losses from the participants, some
  recorded battles and the quarterly war score; the briefing has a line per war
- [x] Live war score (D-044, 2026-11-21): the probe mod's direct value is the war score
  against the enemy war leader, as the game shows it; per ally it cannot be read
- [x] The budget over time (D-053): each snapshot keeps last month's categories; the
  Charts tab draws income by source, recurring expenses and one-off spending, and
  `get_trends` adds how each category moved
- [ ] Let the model reference charts in its answers

## Phase 6 — Claude plays (experimental)

Goal: explore how far the assistant can act, not just advise.

- [x] Advise: structured action recommendations (D-056): `get_recommendations`, a
  ranked list of actions from rules over the save, each with its facts and goals
- [x] Missions whose reward improves later (D-057): the reward's conditions, with the
  current value against the threshold, and a timing recommendation
- [x] Advise: the probe mod's casus belli feed the war targets (D-063)
- [x] Guide: exact UI steps for each recommendation (D-059): a *How* line per
  recommendation, naming the game's screens and buttons in the player's language
- [ ] Act: computer-use prototype that performs approved actions while the game is paused

## Real-time data (prototype, D-044)

- [x] Probe mod: monthly heartbeat, treasury as a control, war score against each enemy
  (direct `trigger_value:war_score` and a `war_score_against` ladder) to `game.log`;
  `chancellor probe install|read`
- [x] First session (2026-11-20, at peace): the monthly pulse and a variable in a log
  line both work; enabled through `dlc_load.json`, since the user skips the launcher
- [x] Casus belli: each type from `common/cb_types` checked with `has_casus_belli`
  against neighbours, rivals and holders of the player's claims or cores
- [x] Casus belli against the diplomacy screen (2026-11-20): the player's own match
  exactly; the subjects' were missing, now checked too
- [x] The subjects' casus belli in game (2026-11-20): Hungary's conquest of Poland found
- [x] A session at war (war score), 2026-11-21: Poland +87 in game, the mod 88 a
  month earlier, the save's quarterly score 87
- [x] The live war score in get_wars and the recommendations (D-063): monthly from the
  probe mod, the quarterly score otherwise; a peace to ask for or to seek
- [x] Casus belli in the war check and the targets (D-051), from the probe mod's log
- [ ] War score in the war check and the briefing, once a session at war confirms it

## Ideas / later

- Ironman support via a token file
- Package as a single executable

### Idea: other models, and no need for a paid Claude plan (2026-11-16)

Started (D-062): LM Studio is configured by `chancellor mcp-config --client lmstudio --write`, and `chancellor eval --model` asks a local model the evaluation questions. **Pending:** a full run with Qwen3 4B (about an hour on the user's laptop, with LM Studio otherwise idle) to measure it.

Was not scheduled. The tools should not require a Claude subscription or the Anthropic API.

- **Cheap step:** MCP is an open protocol, so the server already works with other MCP
  clients, some of them free or running local models (Ollama, LM Studio). Test one,
  document it, and let `mcp-config` write that client's configuration. Which clients
  support local MCP servers well changes quickly: check when doing it.
- **Costlier step, only if worth it:** let the panel's API chat talk to other providers
  through an OpenAI-compatible API. Today `llm.client` is Anthropic-specific (streaming,
  caching, thinking, and the per-model prices of the budget, D-028).
- **Risk:** small and local models handle tools and long results (the briefing) worse,
  so answers would be free but weaker. The computed mechanics in the tools help a
  weaker model most.

### Idea: goal-based watches and a campaign journal (2026-11-13)

(Built so far: the player's context, D-039, the watches, D-041 and D-042, and the
campaign journal, D-043, and goal progress, D-061. Left: watches on events from the
journal (set aside: the game already notifies them), and
watches on events from the journal, such as an ally declaring war or a ruler dying.)

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
