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

**Date:** — · **Status:** Open (Phase 0)

Options: a hand-written Clausewitz parser in Python, an existing Python package, or
bindings to the Rust `eu4save` / `jomini` crates. Decide after measuring on real saves.

## D-004 — Non-ironman only, initially

**Date:** 2026-11-11 · **Status:** Accepted

Ironman saves need a non-public token file. The developer plays non-ironman, so text
saves cover the real use case.

## D-005 — Web-based desktop UI

**Date:** 2026-11-11 · **Status:** Proposed

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
