# CLAUDE.md

Working notes for Claude Code. Keep this file short: it is loaded into every session.
Longer material lives in `docs/` and is read on demand.

## What this project is

**eu4-chancellor** — an AI assistant for Europa Universalis IV. It reads the player's
save files (`.eu4`), extracts the relevant state of the campaign, and lets an LLM answer
questions with that real context. Personal project, built to portfolio quality.
Primary goal: automatic campaign context. Secondary: game + chat in one docked workspace,
charts (PDX Tools-style), and — long term — Claude acting in-game via computer use.

## Conventions (non-negotiable)

- **Everything committed is in English**: code, comments, docstrings, docs, commit messages, issues.
- Spanish notes go in `notes/` (git-ignored). Never commit Spanish content.
- Python 3.11+, `src/` layout, package name `chancellor`.
- Type hints everywhere; docstrings in Google style.
- Lint/format with `ruff`; tests with `pytest`. Run both before declaring work done.
- Never commit `.eu4` files, `.env`, or API keys. Test fixtures are small hand-trimmed snippets only.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`).

## Where things are

| Need | Read |
| --- | --- |
| Current state, traps and next step | `docs/handoff.md` |
| Goals and priorities | `docs/VISION.md` |
| Phases and current task list | `docs/ROADMAP.md` |
| How modules fit together | `docs/ARCHITECTURE.md` |
| Facts about the `.eu4` save format | `docs/SAVE_FORMAT.md` |
| Why a decision was made | `docs/DECISIONS.md` |
| Desktop app layout and views | `docs/UI_DESIGN.md` |

Update those docs in the same change that makes them stale.

## Environment facts (developer machine)

- OS: Windows 11. Paths are set in the local `.env` (git-ignored).
- **Game install (authoritative):** `C:\Games\Europa Universalis IV`. Other EU4 folders may
  exist on this machine from old installs — ignore them.
- **User data / saves:** Documents is redirected to OneDrive, so the game writes to
  `C:\Users\aitzo\OneDrive\Documentos\Paradox Interactive\Europa Universalis IV\save games`
- Game version 1.37 ("Inca"), played in Spanish. The user plays **non-ironman**, so saves
  are plain text.
- Real saves are 5–60 MB. Read them by streaming or with `python -I` scripts; never paste a
  whole gamestate into context.

## Commands

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
chancellor summary          # briefing of the current campaign (uses .env paths)
chancellor country Borgoña  # briefing of any country (tag or name)
chancellor war-check Venecia  # who would fight on each side
chancellor world            # great powers, rankings, alliances, wars
chancellor missions         # mission tree with progress (reads game files)
chancellor decisions --formables  # formable nations with a requirement checklist
chancellor targets          # where to expand: wanted provinces by owner, with war odds
chancellor chat             # talk to the Chancellor (needs ANTHROPIC_API_KEY; billed)
chancellor mcp              # MCP server for Claude Desktop (stdio; never print to stdout)
chancellor mcp-config       # Claude Desktop config entry with absolute paths
chancellor app              # desktop panel (needs: pip install -e ".[ui]")
chancellor clear-cache      # drop cached game data (tests use a temp cache via conftest)
chancellor wiki-import FILE.xml...  # index pages exported from the wiki (Special:Export)
chancellor wiki-search coalition   # search the imported wiki
```

Exploring real saves: load with `chancellor.save.loader.load_save`, then `parse_lazy` and
`.lazy()` / `.parse()` only the blocks you need — a full parse takes ~19 s. Set
`PYTHONIOENCODING=utf-8` when printing names from Git Bash.
