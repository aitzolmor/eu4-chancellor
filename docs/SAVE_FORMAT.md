# EU4 save format notes

Living document. Record verified facts here, with the game version they were observed on.

## Observed on 1.37 ("Inca"), non-ironman

### Two on-disk layouts

| Layout | Seen in | Detection | Contents |
| --- | --- | --- | --- |
| Zip archive | Manual / named saves (~5–8 MB) | `zipfile.is_zipfile()` is true | Entries `meta` (~2 KB), `gamestate` (40–60 MB uncompressed), `ai` (~150 KB) |
| Raw text | `autosave.eu4`, `old_autosave.eu4`, `older_autosave.eu4` (~45 MB) | File starts with `EU4txt` and is not a zip | `meta` and `gamestate` concatenated in a single text file |

Every text entry starts with the magic header `EU4txt`. Ironman saves use `EU4bin` instead.

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

_To be documented in Phase 0._

- [ ] Top-level keys and their approximate sizes
- [ ] `countries` → player block: treasury, manpower, stability, legitimacy, ideas, estates
- [ ] `active_war` / `previous_war`
- [ ] `diplomacy` (alliances, royal marriages, subjects)
- [ ] `provinces`
- [ ] Armies and navies

### Clausewitz syntax summary

- `key=value`, `key={ ... }`, and bare-value lists `{ a b c }`.
- Keys can repeat (e.g. multiple `active_war` blocks) — the parser must keep all occurrences.
- Strings are quoted; numbers, dates and tags are unquoted.
- Encoding is believed to be Windows-1252, not UTF-8 (to verify against names with accents).

## Ironman

Binary format (`EU4bin`) with tokens that map to field names. The token list is not
publicly distributed. Out of scope until a later phase.
