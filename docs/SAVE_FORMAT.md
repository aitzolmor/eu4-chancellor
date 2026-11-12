# EU4 save format notes

Living document. Record verified facts here, with the game version they were observed on.

## Observed on 1.37 ("Inca"), non-ironman

### Two on-disk layouts

| Layout | Seen in | Detection | Contents |
| --- | --- | --- | --- |
| Zip archive | Manual / named saves (~5–8 MB) | `zipfile.is_zipfile()` is true | Entries `meta` (~2 KB), `gamestate` (40–60 MB uncompressed), `ai` (~150 KB) |
| Raw text | `autosave.eu4`, `old_autosave.eu4`, `older_autosave.eu4` (~45 MB) | File starts with `EU4txt` and is not a zip | `meta` and `gamestate` concatenated in a single text file |

Every text entry starts with the magic header `EU4txt`. Ironman saves use `EU4bin` instead.

**Plain-text layout details.** The file is `EU4txt`, then the meta keys, then the
gamestate keys starting at `players_countries=`, then an `ai={...}` block, and a single
`checksum="..."` at the very end. There is no explicit separator: the loader splits at the
first top-level `players_countries=` line. In the zip layout, each entry ends with its own
`checksum` line.

**Encoding.** Verified Windows-1252 (`0xE1` → `á` in `"Náinnas Yugra"`). Strict UTF-8
decoding fails. All 23 local saves decode with zero replacement characters.

**Load performance** (`save.loader.load_save`, 1.37, 38–57 MB gamestates): 0.24–0.41 s
per save, both layouts.

### `meta`

Small header, useful for picking a save without parsing the gamestate:

```text
EU4txt
date=1525.6.30
save_game="autosave.eu4"
player="CAS"
displayed_country_name="Castilla"
savegame_version={ first=1 second=37 third=0 forth=0 name="Inca" }
savegame_versions={ "1.37.0.0" }
dlc_enabled={ "Conquest of Paradise" "Wealth of Nations" ... }
```

- `player` — the player's country tag. Entry point for everything else.
- `date` — in-game date, `YYYY.M.D` without zero padding.

### `gamestate`

About 11 million tokens and 59 top-level keys (Castilla, 1525). Almost all the weight is in
two blocks:

| Key | Size | Contents |
| --- | --- | --- |
| `countries` | ~40 MB | One block per tag (~1,380, including dead/dynamic tags such as `---`) |
| `provinces` | ~12.5 MB | One block per province id; ids are negative (`-1`, `-2`, …) |
| `trade` | ~1.4 MB | Trade nodes |
| `income_statistics`, `nation_size_statistics`, `inflation_statistics`, `score_statistics` | <0.4 MB each | Yearly ledgers per country |
| `diplomacy` | ~0.3 MB | `alliance`, `guarantee`, `dependency` (subjects), `royal_marriage`, `casus_belli`, `war_reparations`, … |
| `active_war` (repeated) | small | Every ongoing war in the world, not just the player's |
| `previous_war` (repeated) | ~0.5 MB | Finished wars |
| `map_area_data` | ~0.1 MB | Written as `map_area_data{` with no `=` |

Other notable top-level keys: `players_countries`, `start_date`, `great_powers`, `empire`
(HRE), `celestial_empire`, `religions`, `institutions`, `trade_league`, `rebel_faction`.

#### Player country (`countries.<TAG>`)

~213 keys. The ones most useful for a briefing:

| Area | Keys |
| --- | --- |
| Identity | `government_name`, `government_rank`, `primary_culture`, `accepted_culture` (repeated), `religion`, `technology_group`, `capital`, `is_great_power` |
| Economy | `treasury`, `estimated_monthly_income`, `ledger`, `inflation`, `corruption`, `loan` (repeated), `estimated_loan`, `mercantilism` |
| Stability | `stability`, `legitimacy`, `prestige`, `war_exhaustion`, `overextension_percentage`, `average_unrest`, `religious_unity` |
| Military | `manpower`/`max_manpower` (thousands), `sailors`/`max_sailors`, `army` and `navy` (repeated), `army_tradition`, `navy_tradition`, `army_professionalism`, `leader` (repeated), `mercenary_company` (repeated) |
| Development | `development`, `raw_development`, `num_of_cities`, `owned_provinces`, `core_provinces`, `claim_provinces` |
| Diplomacy | `allies`, `subjects`, `rival` (repeated), `enemy` (repeated), `neighbours`, `friend_tags`, `coalition_against_us` (repeated), `active_relations` |
| Progress | `technology` (`adm_tech`/`dip_tech`/`mil_tech`), `active_idea_groups`, `government` (reforms), `estate` (repeated), `completed_missions`, `innovativeness`, `splendor` |
| Ruler | `monarch` and `heir` hold only `{ id type }` references (see below) |

Values such as `manpower=33.343` are in thousands; `overextension_percentage=0.312` and
`army_professionalism=0.445` are ratios. `sailors` is an absolute number.

#### Resolving references

- **Ruler and heir.** `monarch={ id=15670 type=48 }` points into the country's own
  `history`. Dated entries contain `monarch`, `heir` or `monarch_heir` blocks with the full
  person: `name`, `dynasty`, `ADM`/`DIP`/`MIL`, `birth_date`, `personalities`, … Match on
  `id.id` and keep the latest record. A date key can repeat, so read it with `get_all`.
  Elective monarchies (Poland, Lithuania) record rulers chosen abroad under
  `foreign_heir`. Across all 23 local saves, 0.6% of living countries' rulers
  (68 of 11,826) are still not found under any known key.
- **Leaders and advisors.** `leader` / `advisor` are also `{ id type }` references.
  Leader details appear in `history` dated entries (`leader={ name type fire shock … }`).
  Advisor details are not resolved yet.

#### Armies and navies

`army` (repeated): `name`, `location` (province id), `leader` reference, and `regiment`
(repeated) with `type`, `morale`, `home`. Strength per regiment is not stored when full.
`navy` has the same shape with `ship`. Totals by unit category are cached in
`num_subunits_type_and_cat={ infantry={ normal=28 } cavalry={…} … }`.

#### Estates, relations and money

- `estate` (repeated): `type` (`estate_church`, …), `loyalty`, `territory` (land share %),
  `granted_privileges`, `influence_modifier`. Total influence is computed, not stored.
- `active_relations.<TAG>`: this country's view of another: `cached_sum` (opinion),
  `attitude` (`attitude_rivalry`, …), and the `opinion` modifiers. To get "their opinion
  of us", read the *other* country's `active_relations.<player tag>`.
- `ledger`: `lastmonthincome` / `lastmonthexpense` totals and per-category arrays
  (`lastmonthincometable`, …). The index → category mapping is not documented yet.
- `loan` (repeated): `amount`, `interest`, `expiry_date`, `lender`.

#### Wars (`active_war`, repeated)

`name` (often with a leading space), `attackers` / `defenders` (current tags),
`original_attacker` / `original_defender`, `participants` (each with `tag`, participation
`value` and `losses.members`, a 21-slot array), `take_province` (war goal: `type`,
`province`, `casus_belli`), `action` (start date), and `history` (dated join/leave
events). **War score is not stored** in the save; it must be estimated or left to the
player.

#### Diplomacy block

`dependency` entries have `first` (overlord), `second` (subject) and `subject_type`
(`personal_union`, `march`, `vassal`, …). `royal_marriage`, `alliance` and `guarantee`
use the same `first`/`second` shape.

#### Dynamic countries

Colonial nations and other generated tags (`C00`, `D01`, …) have no localisation entry;
their display name is stored in the country block as `name`.

### Clausewitz syntax summary

- `key=value`, `key={ ... }`, and bare-value lists `{ a b c }`.
- `key{ ... }` without `=` also occurs (`map_area_data`).
- Keys can repeat (e.g. multiple `active_war` blocks) — the parser must keep all occurrences.
- Strings are quoted; numbers, dates and tags are unquoted. Booleans are `yes`/`no`.
- **Indentation is not reliable**: some nested blocks are written at column 0, so section
  boundaries must be found by counting braces, never by indentation.
- No comments or escaped quotes appear in saves (they do in game data files).
- Encoding is Windows-1252, not UTF-8 (see above).

### Parsing performance (pure Python, 57 MB gamestate)

| Operation | Time |
| --- | --- |
| Tokenise whole gamestate (11.3 M tokens) | 4.8 s |
| Full parse | 19 s |
| `parse_lazy` top level | 1.4 s |
| `countries` one level deep | 0.9 s |
| Full parse of one country | 0.02 s |

Hence D-008: parse lazily and only what is needed.

## Related files outside the save

### Locating the user data folder

The install folder's `launcher-settings.json` declares
`"gameDataPath": "%USER_DOCUMENTS%/Paradox Interactive/Europa Universalis IV"`.
`%USER_DOCUMENTS%` is the Windows *Documents* known folder, which may be redirected
(e.g. to OneDrive). Resolve it via the OS rather than assuming `~/Documents`.

### `continue_game.json`

Lives in the user data folder and points at the save the game would resume:

```json
{ "title": "Austria 1475.06.21", "date": "Tue Nov 10 21:23:34 2026\n",
  "filename": "save games/Austria1475_06_21.eu4" }
```

A better signal of "the current campaign" than file modification time, because
autosaves rotate and may belong to a different playthrough.

### Localisation

`<game_dir>/localisation/*_l_<language>.yml` maps tags and keys to display names
(e.g. `countries_l_spanish.yml`: `ADE:1 "Adén"`). Files are UTF-8 with a BOM.
Province names use `PROV<id>` keys (`PROV219` → "Toledo"). The full Spanish set is
~129k entries and loads in ~2.3 s.

The player's game language is in the user data folder's `settings.txt`:
`language="l_spanish"`.

## Ironman

Binary format (`EU4bin`) with tokens that map to field names. The token list is not
publicly distributed. Out of scope until a later phase.
