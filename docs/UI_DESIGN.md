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
1493×933 logical pixels), where EU4 runs borderless, and at times a second screen at
1920×1080 (a cabled monitor, or a second laptop through Windows' *Project to this PC*,
Miracast, which Windows treats as an extended display). The game's window is never
moved or resized: EU4 draws at its own resolution and ignores outside resizing (D-022).

**Two screens** (preferred when available): EU4 keeps its whole screen; the Chancellor
panel and Claude Desktop are docked side by side on the other one (panel a third,
Claude Desktop the rest). *Dock beside the game* arranges them; *Undock* puts them back.

**One screen**: nothing is split. A floating icon (a gold crown in a navy circle) sits
over the game, always on top, and can be dragged anywhere. A click opens an overlay
column on the icon's side of the screen: the panel on top, Claude Desktop below, both
above the game. Another click, *Back to the game* or `Esc` puts them away (Claude
Desktop drops behind the game). A right-click offers *Close Chancellor*. The icon is a
native window with real per-pixel transparency (D-023), so only the circle shows. It
is shown only while the game is the active
window, while the overlay is open, or when the game is not running; it hides when the
player switches to another program.

```
┌──────────────────────────────────────────────┬──────────────────────┐
│                                              │  Chancellor panel    │
│                                              │  (overlay, on top)   │
│                 Europa Universalis IV        ├──────────────────────┤
│                 borderless, full screen      │                      │
│                                         (o)  │  Claude Desktop      │
│                                    icon ─┘   │  (overlay, on top)   │
│                                              │                      │
└──────────────────────────────────────────────┴──────────────────────┘
```

The column is 40% of the screen wide, or wider if Claude Desktop will not shrink that
far (about 600 logical pixels): the app measures what it accepted and lines the panel
up with it.

All placement works in physical pixels with a per-monitor DPI-aware process, so the
150% scaling does not shift windows. Windows are found by process (`eu4.exe`,
`claude.exe`) and moved with Win32 calls (`SetWindowPos`), never reparented (D-006).

## The Chancellor panel

> Future direction (ROADMAP, *Idea: goal-based watches and a campaign journal*): the key
> numbers and alerts below largely repeat the game's own screens. The panel's lasting
> value is likely watches tied to the player's goals, goal progress and a journal of
> changes between saves. The current layout stays until that is designed.

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

- Miracast displays add latency and can drop; the app decides one or two screens at
  start, and should follow a screen appearing or disappearing while it runs.
- Whether a global hotkey can be registered while EU4 has focus. EU4 runs as
  administrator on the developer's machine, and Windows hides input state from normal
  programs while an elevated window is in front (D-022); `RegisterHotKey` may still
  work, to be verified.

## Build order

1. Panel window with the header and key numbers, reading the current save (no docking).
   **Done** (`chancellor app`).
2. Watcher and live refresh. **Done** (`chancellor.watcher.SaveWatcher`).
3. Alerts. **Done** (`chancellor.context.alerts`); "new missions or formables since the
   previous save" is left for later, since it needs the previous save's state.
4. Docking on two screens and the floating icon with an overlay on one (D-022).
   **Done** (`chancellor.app.layout`). Verified live: on two screens the panel and
   Claude Desktop land pixel-exact on the second one and undock restores them; on one
   screen, with EU4 in front and running as administrator, the icon drags, opens and
   closes the overlay, hides when the game is not in front, and quits. Not verified
   yet: Miracast, a screen dropping or appearing while the app runs, and remembering
   where the icon was left.
5. Quick questions; overlay hotkey.
6. API chat tab behind the chat-mode switch.
7. Charts and history (Phase 5).
