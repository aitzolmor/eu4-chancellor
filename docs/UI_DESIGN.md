# Desktop app design

Design of the Chancellor's desktop window (Phase 4, `app.ui`). It records what the window
does, how it is laid out and how it fits the existing backend. Decisions behind it:
D-006 (docked layout), D-020 (hybrid chat, API only on the player's request) and D-021
(shell and frontend).

## Goals

1. **Game and assistant feel like one workspace** (VISION, secondary goal 1): EU4 and the
   assistant share the screen without alt-tabbing.
2. **Campaign awareness at a glance**: which save the assistant reads, and what needs
   attention (truces ending, coalitions, overextension, an imperial reform ready).
3. **No spending without consent**: the chat costs nothing by default. The paid API chat
   is a mode the player turns on, never something the app picks.
4. **Room to grow**: charts and save history (Phase 5) and computer use (Phase 6) fit
   into the same window later.

Non-goals for the first version: drawing over the game's DirectX surface, embedding the
game window, a custom chat UI that replaces Claude Desktop.

## Hybrid chat (D-020)

| Chat mode | Where the chat runs | Cost | Default |
| --- | --- | --- | --- |
| **Claude Desktop** | Claude Desktop, docked beside the game, using the Chancellor's tools through MCP | Covered by the Claude subscription | Yes |
| **API** | A chat tab inside the Chancellor's window, driven by `ChancellorAgent` | Billed per question | Off; only the player turns it on |

Rules for the API mode:

- It is switched on only by an explicit action of the player: the chat-mode switch in the
  header. Nothing switches it on automatically, and there is no fallback to the API when
  Claude Desktop is missing or busy.
- Turning it on asks for confirmation once per session, saying it is billed per question
  and showing the model and effort in use.
- While it is on, the header shows a visible "API, billed" badge and a running count of
  questions and tokens for the session.
- Without `ANTHROPIC_API_KEY` the switch is disabled, with a tooltip saying why.
- The choice is remembered only for the session; every launch starts in Claude Desktop
  mode.

## Screen layout

The developer's setup (2026-11-13): a main laptop at 2240×1400 with 150% scaling (about
1493×933 logical pixels), where EU4 runs borderless, and at times a second laptop at
1920×1080 showing a window from the first. With one screen, a 30% column is only about
450 logical pixels, too narrow for Claude Desktop, so the layout depends on how many
screens Windows reports:

- **Two screens** (preferred when available): EU4 keeps the whole main screen; the
  Chancellor panel and Claude Desktop share the second screen side by side (panel about
  a third, Claude Desktop the rest).
- **One screen**: the split below, with the panel and Claude Desktop stacked in the
  right-hand column; the overlay mode suits it better when the column is too narrow.

All placement works in physical pixels with a per-monitor DPI-aware process, so the
150% scaling does not shift windows. The second laptop receives the main laptop's
screen through Windows' *Project to this PC* (Miracast), which Windows treats as an
extended display, so it can host docked windows; to be verified when docking is built.

One-screen split (proportions, so any resolution scales the same way):

```
┌──────────────────────────────────────────────┬──────────────────────┐
│                                              │  Chancellor panel    │
│                                              │  (status, alerts,    │
│                 Europa Universalis IV        │   quick actions)     │
│                 borderless window            ├──────────────────────┤
│                 ~70% of the width            │                      │
│                                              │  Chat column         │
│                                              │  Claude Desktop      │
│                                              │  (or the API tab)    │
│                                              │                      │
└──────────────────────────────────────────────┴──────────────────────┘
```

- **Docked** (default): the app moves and resizes three top-level windows: EU4 on the
  left, the Chancellor panel at the top right, Claude Desktop below it. In API mode the
  chat tab takes the panel's lower part and Claude Desktop is left alone.
- **Overlay**: a global hotkey (proposed `Ctrl+Shift+Space`) shows the panel always on
  top over a full-width game, and hides it again. For players who prefer the game full
  screen.
- **Undocked**: the panel is an ordinary window; nothing else is moved.

EU4 must run in *borderless windowed* mode (a game setting); the app checks the window
style and explains how to switch if it finds an exclusive full-screen window. Windows
are found by process (`eu4.exe`, Claude Desktop's package) and moved with Win32 calls
(`SetWindowPos`), never reparented (D-006).

## The Chancellor panel

From top to bottom:

1. **Header**: country name and tag, in-game date, save file name, "read 2 min ago",
   the chat-mode switch and, in API mode, the billed badge.
2. **Alerts**: short, ranked lines from data the tools already produce, each linking to
   the full view:
   - a truce with a rival ends soon (estimated, D-017);
   - coalition members and the countries at 50+ aggressive expansion;
   - overextension above 0%, war exhaustion, loans;
   - an imperial reform can be proposed (authority ≥ 50);
   - a mission or formable became available since the previous save.
3. **Key numbers**: treasury and monthly balance, manpower, stability, monarch power,
   army size against rivals.
4. **Quick questions**: buttons such as "How is my campaign going?" or "Where should I
   expand?". In Claude Desktop mode they copy the question to the clipboard and bring
   Claude Desktop to the front; in API mode they send it to the chat tab.
5. **Footer**: dock / overlay / undock, settings.

Later tabs: **Charts** and **History** (Phase 5), **API chat** (when the mode is on).

## Architecture

```
pywebview window ──(js_api calls)──► chancellor.app.ui.Api ──► context.* queries
      ▲                                     │                    (same Toolbox as MCP)
      └──────(evaluate_js events)───────────┤
                                            ├──► watcher thread: new save → reload → push
                                            ├──► app.layout: find, move and size windows
                                            └──► llm.client.ChancellorAgent (API mode only)
```

- `app.ui`: creates the window and a small `Api` object whose methods the page calls
  (`status()`, `alerts()`, `dock()`, `set_chat_mode()`, ...). Results are JSON built from
  the existing dataclasses; Markdown renderers stay for the CLI and the tools.
- `watcher`: polls the save folder (as `CampaignProvider` does for MCP), reloads on a new
  save and pushes a `save-changed` event to the page.
- `app.layout`: Win32 window handling through `ctypes`; no extra dependency.
- Frontend: plain HTML, CSS and JavaScript modules under `src/chancellor/app/web/`, no
  build step. Libraries (charts later) are vendored files, so the app works offline.
- Long calls (loading a 60 MB save, a war check) run off the UI thread; the page shows
  a loading state and never freezes.

## Visual direction

The panel sits next to a dark, ornate game, so it is dark by default with a light theme
available: deep navy surfaces, parchment-coloured text, a single gold accent for focus
and alerts, compact type (13–14 px), no animation beyond state changes. It should read
as a calm instrument panel, not compete with the map.

## Open questions

- Claude Desktop's minimum window width may not fit the one-screen column at 150%
  scaling; measure it before fixing the split.
- Miracast displays add latency and can drop; docking should survive the second screen
  disappearing (fall back to the one-screen layout).
- Whether a global hotkey can be registered while EU4 has focus without elevated rights
  (`RegisterHotKey` should work; to be verified).

## Build order

1. Panel window with the header and key numbers, reading the current save (no docking).
   **Done** (`chancellor app`).
2. Watcher and live refresh. **Done** (`chancellor.watcher.SaveWatcher`).
3. Alerts.
4. Docked layout with EU4 and Claude Desktop; undock.
5. Quick questions; overlay hotkey.
6. API chat tab behind the chat-mode switch.
7. Charts and history (Phase 5).
