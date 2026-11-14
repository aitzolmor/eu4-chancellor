// The Chancellor panel: asks Python for the campaign's key facts and lays them out.
// Python side: chancellor.app.ui.PanelApi, reached through pywebview's js_api bridge.

import { renderMarkdown } from "./markdown.js";

const $ = (id) => document.getElementById(id);
let readAt = null;
let loading = false;

const number = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });

function signed(value, format = number) {
  const text = format.format(Math.abs(value));
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text;
}

function thousands(men) {
  return men >= 1000 ? `${oneDecimal.format(men / 1000)}k` : number.format(men);
}

function show(section) {
  for (const id of ["loading", "error", "numbers"]) $(id).hidden = id !== section;
  $("alerts-section").hidden = section !== "numbers";
}

function renderAlerts(alerts) {
  const list = $("alerts");
  list.replaceChildren();
  for (const alert of alerts) {
    const item = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = `dot ${alert.severity}`;
    dot.setAttribute("aria-label", alert.severity);
    const text = document.createElement("span");
    text.textContent = alert.text;
    item.append(dot, text);
    list.append(item);
  }
  $("alerts-loading").hidden = alerts.length > 0;
  setText("alerts-loading", alerts.length ? "" : "Nothing urgent.");
}

async function loadAlerts() {
  setText("alerts-loading", "Checking…");
  $("alerts-loading").hidden = false;
  try {
    const result = await window.pywebview.api.alerts();
    if (result.ok) renderAlerts(result.alerts);
    else setText("alerts-loading", `Alerts unavailable: ${result.error}`);
  } catch (error) {
    setText("alerts-loading", `Alerts unavailable: ${error}`);
  }
}

function setText(id, text, tone = null) {
  const element = $(id);
  element.textContent = text ?? "";
  element.classList.remove("positive", "negative");
  if (tone) element.classList.add(tone);
}

function ago(seconds) {
  if (seconds < 60) return "read just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `read ${minutes} min ago`;
  return `read ${Math.round(minutes / 60)} h ago`;
}

function renderMeta(status) {
  const parts = [status.date];
  if (status.save_name) parts.push(status.save_name);
  if (readAt !== null) parts.push(ago(Date.now() / 1000 - readAt));
  setText("meta", parts.join(" · "));
}

function render(status) {
  setText("country", `${status.name} (${status.tag})`);
  renderMeta(status);

  setText("treasury", status.treasury === null ? "?" : `${number.format(status.treasury)} ducats`);
  if (status.income !== null && status.expenses !== null) {
    const balance = status.income - status.expenses;
    setText("balance", `${signed(balance, oneDecimal)} a month`, balance < 0 ? "negative" : "positive");
  } else {
    setText("balance", "");
  }

  setText("manpower", status.manpower === null ? "?" : thousands(status.manpower));
  setText("manpower-max", status.max_manpower === null ? "" : `of ${thousands(status.max_manpower)}`);
  setText("regiments", number.format(status.regiments));
  setText("loans", status.loans ? `${status.loans} loan${status.loans === 1 ? "" : "s"}` : "", status.loans ? "negative" : null);

  const stability = status.stability ?? 0;
  setText("stability", signed(stability), stability < 0 ? "negative" : null);
  setText("legitimacy", status.legitimacy === null ? "" : `legitimacy ${number.format(status.legitimacy)}`);
  setText("prestige", status.prestige === null ? "?" : number.format(status.prestige));
  setText("rank", status.great_power_rank ? `great power #${status.great_power_rank}` : "");
  setText("development", status.development === null ? "?" : number.format(status.development));
  setText("powers", status.monarch_power ? status.monarch_power.join(" / ") : "?");
  setText("wars", status.wars.length ? status.wars.join(", ") : "At peace");
  show("numbers");
}

let lastStatus = null;

async function load() {
  if (loading) return;
  loading = true;
  $("refresh").classList.add("busy");
  if (!lastStatus) show("loading");
  try {
    const result = await window.pywebview.api.status();
    if (result.ok) {
      readAt = result.read_at;
      lastStatus = result.status;
      render(result.status);
      loadAlerts(); // slower (aggressive expansion scan); the numbers show first
    } else {
      setText("error-text", result.error);
      show("error");
    }
  } catch (error) {
    setText("error-text", `The panel could not reach the Chancellor: ${error}`);
    show("error");
  } finally {
    loading = false;
    $("refresh").classList.remove("busy");
  }
}

// Python's SaveWatcher fires this once the game has finished writing a new save.
window.addEventListener("save-changed", (event) => {
  const name = event.detail?.save;
  setText("meta", name ? `New save ${name}, reading…` : "New save, reading…");
  load();
});

// --- Status line -----------------------------------------------------------------------
// One line under the header for results and errors; hidden when there is nothing to say.
// Results fade after a while; errors stay until the next action.
let statusTimer = null;

function status(text, tone = null) {
  const line = $("status");
  clearTimeout(statusTimer);
  line.textContent = text ?? "";
  line.classList.toggle("error", tone === "error");
  line.hidden = !text;
  if (text && tone !== "error" && tone !== "busy") {
    statusTimer = setTimeout(() => { line.hidden = true; }, 6000);
  }
}

// --- Menu ------------------------------------------------------------------------------
// Docking, the way back to the game and the overlay side are used now and then, so they
// live behind the "…" button instead of taking room while playing.
function setMenu(open) {
  $("menu").hidden = !open;
  $("menu-button").setAttribute("aria-expanded", String(open));
  if (open) $("menu").querySelector("button:not([hidden])")?.focus();
}

$("menu-button").addEventListener("click", (event) => {
  event.stopPropagation();
  setMenu($("menu").hidden);
});
document.addEventListener("click", (event) => {
  if (!$("menu").hidden && !$("menu").contains(event.target)) setMenu(false);
});

const DOCK_MODES = {
  two_screens: "Docked: panel and Claude Desktop on the second screen.",
  one_screen: "Docked: game on the left, panel and Claude Desktop on the right.",
};

async function dock() {
  setMenu(false);
  status("Docking…", "busy");
  const result = await window.pywebview.api.dock();
  if (!result.ok) {
    status(result.error, "error");
    return;
  }
  let text = DOCK_MODES[result.mode] ?? "Docked.";
  if (!result.game_found) text += " EU4 is not running; start it in borderless windowed mode.";
  status(text);
  $("undock").hidden = false;
}

async function undock() {
  setMenu(false);
  await window.pywebview.api.undock();
  $("undock").hidden = true;
  status("Windows are back where they were.");
}

function closeOverlay() {
  setMenu(false);
  window.pywebview.api.toggle_overlay();
}

$("dock").addEventListener("click", dock);
$("undock").addEventListener("click", undock);
$("close-overlay").addEventListener("click", closeOverlay);
$("refresh").addEventListener("click", load);
$("retry").addEventListener("click", load);
setInterval(() => lastStatus && renderMeta(lastStatus), 30_000);

// The mode can change while the app runs: a second screen appearing or dropping. With
// one screen the panel opens over the game from the floating icon (D-022), so the menu
// offers the way back and the overlay side instead of docking.
let overlayMode = false;

async function setUpLayout() {
  const { mode, docked, side } = await window.pywebview.api.layout_mode();
  overlayMode = mode === "overlay";
  document.body.classList.toggle("overlay", overlayMode);
  $("side-row").hidden = !overlayMode;
  showSide(side);
  $("dock").hidden = overlayMode;
  $("undock").hidden = overlayMode || !docked;
  $("close-overlay").hidden = !overlayMode;
}

// One screen: the player picks the side the overlay opens on, to keep the part of the
// game's interface they need in view. It does not follow the floating icon.
function showSide(side) {
  for (const name of ["left", "right"]) {
    $(`side-${name}`).setAttribute("aria-pressed", String(side === name));
  }
}

async function chooseSide(side) {
  const result = await window.pywebview.api.set_overlay_side(side);
  if (result.ok) showSide(result.side);
  else status(result.error, "error");
}

$("side-left").addEventListener("click", () => chooseSide("left"));
$("side-right").addEventListener("click", () => chooseSide("right"));

window.addEventListener("layout-changed", async () => {
  await setUpLayout();
  setUpHotkey();
});

// Escape closes the menu first; with the menu closed it puts the overlay away.
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!$("menu").hidden) {
    setMenu(false);
    $("menu-button").focus();
  } else if (overlayMode) {
    closeOverlay();
  }
});

// --- Quick questions (build order step 5) ----------------------------------------------
// In Claude Desktop mode Python copies the prompt and brings Claude Desktop forward; the
// player pastes it there. With the API chat on, the question goes to the chat tab.
async function ask(question, button) {
  if (chat.mode === "api") {
    showTab("chat");
    sendToApi(question.prompt);
    return;
  }
  status("Copying…", "busy");
  const result = await window.pywebview.api.ask(question.id);
  for (const other of $("questions").children) other.classList.remove("sent");
  if (!result.ok) {
    status(result.error, "error");
    return;
  }
  button.classList.add("sent");
  if (result.focused) status(`Copied "${question.label}". Paste it in Claude Desktop with Ctrl+V.`);
  else status(`Copied, but Claude Desktop could not be opened: ${result.error}`, "error");
}

async function setUpQuestions() {
  const { questions } = await window.pywebview.api.quick_questions();
  const box = $("questions");
  box.replaceChildren();
  for (const question of questions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = question.label;
    button.title = question.prompt;
    button.addEventListener("click", () => ask(question, button));
    box.append(button);
  }
}

async function setUpHotkey() {
  const hotkey = await window.pywebview.api.hotkey();
  const hint = $("menu-hotkey");
  hint.hidden = !hotkey.registered;
  if (!hotkey.registered) return;
  const keys = document.createElement("kbd");
  keys.textContent = hotkey.keys;
  const what = overlayMode ? "opens or closes this panel over the game." : "brings Claude Desktop forward.";
  hint.replaceChildren(keys, ` ${what}`);
}

// --- API chat (build order step 6, D-020, D-028) ---------------------------------------
// Off by default and only for this session. Turning it on asks once per session; while it
// is on, the header shows what has been spent of the budget.
let chat = { mode: "claude_desktop" };
let confirmedThisSession = false;
let answer = null; // the assistant bubble being streamed: { text, body, tools, frame }

const dollars = (value) => `$${Number(value ?? 0).toFixed(2)}`;
// One question usually costs cents: show a tenth of a cent.
const cents = (value) => `$${Number(value ?? 0).toFixed(3)}`;

function showChatMode(state) {
  chat = { ...chat, ...state };
  const on = chat.mode === "api";
  $("chat-desktop").setAttribute("aria-pressed", String(!on));
  $("chat-api").setAttribute("aria-pressed", String(on));
  $("chat-api").disabled = !on && !chat.api_available;
  $("chat-api").title = chat.api_available ? "" : chat.reason ?? "";
  $("api-badge").hidden = !on;
  setText("api-badge", `API · ${dollars(chat.spent)} of ${dollars(chat.budget)} spent`);
  setText(
    "chat-hint",
    on
      ? `API chat on: ${chat.model}, up to ${dollars(chat.question_cap)} a question.`
      : "The chat runs in Claude Desktop and reads the same save.",
  );
  $("tabs").hidden = !on;
  if (!on) showTab("campaign");
  setBusy(Boolean(chat.busy));
}

function showTab(name) {
  const onChat = name === "chat" && chat.mode === "api";
  $("tab-campaign").setAttribute("aria-selected", String(!onChat));
  $("tab-chat").setAttribute("aria-selected", String(onChat));
  $("content").hidden = onChat;
  $("ask").hidden = onChat;
  $("chat").hidden = !onChat;
  if (onChat) $("chat-input").focus();
}

function askToTurnOn() {
  const text =
    `Each question is billed to your API key: ${chat.model}, effort ${chat.effort}, ` +
    `up to ${dollars(chat.question_cap)} a question. ${dollars(chat.spent)} of ` +
    `${dollars(chat.budget)} spent so far. It stays on until you switch back or close the app.`;
  setText("api-confirm-text", text);
  $("api-confirm").hidden = false;
  $("api-confirm-yes").focus();
}

async function setChatMode(mode) {
  $("api-confirm").hidden = true;
  const result = await window.pywebview.api.set_chat_mode(mode);
  if (!result.ok) {
    status(result.error, "error");
    return;
  }
  showChatMode(result);
  if (mode === "api") {
    setMenu(false);
    showTab("chat");
    status("API chat on: questions are billed.");
  } else {
    status("Back to Claude Desktop.");
  }
}

$("chat-desktop").addEventListener("click", () => setChatMode("claude_desktop"));
$("chat-api").addEventListener("click", () => {
  if (chat.mode === "api") return;
  if (confirmedThisSession) setChatMode("api");
  else askToTurnOn();
});
$("api-confirm-yes").addEventListener("click", () => {
  confirmedThisSession = true;
  setChatMode("api");
});
$("api-confirm-no").addEventListener("click", () => {
  $("api-confirm").hidden = true;
});
$("tab-campaign").addEventListener("click", () => showTab("campaign"));
$("tab-chat").addEventListener("click", () => showTab("chat"));

function setBusy(busy) {
  $("chat-send").disabled = busy;
  $("chat-send").textContent = busy ? "Answering…" : "Send";
}

function bubble(role, text = "") {
  $("chat-empty").hidden = true;
  const item = document.createElement("article");
  item.className = `bubble ${role}`;
  const tools = document.createElement("p");
  tools.className = "tools";
  tools.hidden = true;
  const body = document.createElement("div");
  body.className = "body";
  if (role === "user") body.textContent = text;
  item.append(tools, body);
  $("chat-log").append(item);
  item.scrollIntoView({ block: "end" });
  return { item, body, tools };
}

function renderAnswer() {
  if (!answer) return;
  answer.frame = null;
  answer.body.innerHTML = renderMarkdown(answer.text);
  answer.item.scrollIntoView({ block: "end" });
}

async function sendToApi(question) {
  const text = question.trim();
  if (!text) return;
  bubble("user", text);
  const pending = bubble("assistant");
  pending.body.innerHTML = '<p class="quiet">Thinking…</p>';
  answer = { ...pending, text: "", frame: null };
  setBusy(true);
  const result = await window.pywebview.api.ask_api(text);
  if (!result.ok) {
    answer.body.innerHTML = "";
    answer.body.append(Object.assign(document.createElement("p"), { className: "error", textContent: result.error }));
    answer = null;
    setBusy(false);
  }
}

window.addEventListener("chat-delta", (event) => {
  if (!answer) return;
  answer.text += event.detail.text;
  if (!answer.frame) answer.frame = requestAnimationFrame(renderAnswer);
});

window.addEventListener("chat-tool", (event) => {
  if (!answer) return;
  answer.tools.hidden = false;
  const chip = document.createElement("span");
  chip.textContent = event.detail.name.replaceAll("_", " ");
  answer.tools.append(chip);
});

window.addEventListener("chat-done", (event) => {
  const { cost, note } = event.detail;
  if (answer) {
    renderAnswer();
    if (note) answer.body.append(Object.assign(document.createElement("p"), { className: "note", textContent: note }));
    answer.item.append(Object.assign(document.createElement("p"), { className: "cost", textContent: cents(cost) }));
    answer = null;
  }
  showChatMode(event.detail);
});

window.addEventListener("chat-error", (event) => {
  if (answer) {
    renderAnswer();
    answer.body.append(Object.assign(document.createElement("p"), { className: "error", textContent: event.detail.error }));
    answer = null;
  }
  showChatMode(event.detail);
});

$("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if ($("chat-send").disabled) return;
  const input = $("chat-input");
  sendToApi(input.value);
  input.value = "";
});

// Enter sends, Shift+Enter starts a new line.
$("chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("chat-form").requestSubmit();
  }
});

async function start() {
  await setUpLayout();
  setUpQuestions();
  setUpHotkey();
  showChatMode(await window.pywebview.api.chat_mode());
  load();
}

// The bridge may be ready before this module runs; then the event has already fired.
if (window.pywebview?.api?.status) start();
else window.addEventListener("pywebviewready", start);
