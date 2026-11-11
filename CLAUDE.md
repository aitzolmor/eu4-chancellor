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
| Goals and priorities | `docs/VISION.md` |
| Phases and current task list | `docs/ROADMAP.md` |
| How modules fit together | `docs/ARCHITECTURE.md` |
| Facts about the `.eu4` save format | `docs/SAVE_FORMAT.md` |
| Why a decision was made | `docs/DECISIONS.md` |

Update those docs in the same change that makes them stale.

## Environment facts (developer machine)

- OS: Windows 11. Saves live under OneDrive:
  `C:\Users\aitzo\OneDrive\Documentos\Paradox Interactive\Europa Universalis IV\save games`
- Game version 1.37 ("Inca"). The user plays **non-ironman**, so saves are plain text.
- Real saves are 5–60 MB. Read them by streaming or with `python -I` scripts; never paste a
  whole gamestate into context.

## Commands

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
chancellor --help
```
