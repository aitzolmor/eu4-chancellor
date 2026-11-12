# Vision

What eu4-chancellor is trying to achieve, in priority order. Details are refined as
development progresses; this document captures intent, not implementation.

## Primary goal — automatic campaign context

The player should be able to ask Claude anything mid-campaign **without describing their
situation**. The application reads the latest save, extracts what matters, and hands it to
the model automatically. Every other goal builds on this one.

Success looks like: save the game, ask "can I afford to declare war on Burgundy?", and get
an answer grounded in the actual treasury, armies, allies and war score.

### Context is not only "my country"

Players ask about the whole world, not just their own realm:

- **Any country.** "Is it worth attacking a country on the other side of Europe?" needs
  that country's strength, allies and situation, not only the player's.
- **War feasibility.** Who would defend the target (allies, guarantors, overlord, the
  Emperor), how strong that coalition is, and whose side shared allies would take.
- **The world state.** Great powers, alliance blocs and major wars shape every plan.

So context is built from **queries** that can be pointed at any country or question. Each
query returns structured data: the CLI renders it as Markdown today, and the chat agent
calls the same functions as tools later, so the player never has to paste context by hand.

### Game knowledge for long-term planning

"What is the ideal plan for my country for the next 200 years?" cannot be answered from the
save alone. The assistant also needs to know the game's content: mission trees, events,
decisions, formable nations, idea groups. Then it must **cross that knowledge with the
current world state**.

Example: Austria's usual path is to integrate Bohemia and Hungary and take Burgundy. In a
given campaign, though, Burgundy may be allied with two great powers, which makes that war
a bad idea for now. A good plan is the standard route filtered by what is actually
happening in the game.

Sources, in order of preference:

1. **Game files** from the player's installation (`missions/`, `events/`, `decisions/`,
   `common/`). They match the installed version exactly and use the same Clausewitz
   syntax the save parser already reads.
2. **The EU4 wiki** for strategy and mechanics explanations, as a complement.

## Secondary goals

### 1. Comfort — one workspace for game and chat

The game and the assistant should feel like a single application. Embedding a chat *inside*
EU4 is not possible (mods cannot make network requests), so the approach is the reverse:
the assistant becomes the workspace and arranges the game around it.

Realistic options, in order of preference:

| Approach | Description | Assessment |
| --- | --- | --- |
| Docked layout | The app positions EU4 as a borderless window in most of the screen and docks its own panel beside it | Robust; feels like one app. **Preferred.** |
| Overlay | Translucent always-on-top panel over the game, toggled by a global hotkey | Complements the docked layout |
| Window embedding / capture | Reparent the EU4 window (Win32 `SetParent`) or stream a capture of it | Fragile with DirectX, input and fullscreen; experiment only |

### 2. Insight — charts and visual analysis

Show campaign data visually, in the spirit of [PDX Tools](https://pdx.tools): income and
expense breakdowns, army strength, development, and — something PDX Tools does not do
with a local history — **trends across the player's own saves** over time.

Options range from linking or embedding PDX Tools in a tab, to building our own charts from
the data the parser already produces. This goal is the main reason the UI is planned as a
web-based desktop app (see D-005 in [DECISIONS.md](DECISIONS.md)).

### 3. Long-term experiment — Claude plays

Far-future idea, kept on the map because it is worth trying. A gradual ladder:

1. **Advise** — Claude recommends concrete actions.
2. **Guide** — Claude lists the exact UI steps to carry them out.
3. **Act** — Claude performs them through computer use (screenshots and clicks) while the
   game is paused, with the player approving each step.

Game mods cannot talk to the outside world, so screen-level control is the only channel for
acting. It is expected to be slow and costly; the value is in the experiment itself.

## Non-goals (for now)

- Ironman save support.
- Multiplayer or sharing features.
- Supporting Europa Universalis V or other Paradox titles.
