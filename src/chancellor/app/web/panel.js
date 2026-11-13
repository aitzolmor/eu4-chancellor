// The Chancellor panel: asks Python for the campaign's key facts and lays them out.
// Python side: chancellor.app.ui.PanelApi, reached through pywebview's js_api bridge.

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

$("refresh").addEventListener("click", load);
$("retry").addEventListener("click", load);
setInterval(() => lastStatus && renderMeta(lastStatus), 30_000);
// The bridge may be ready before this module runs; then the event has already fired.
if (window.pywebview?.api?.status) load();
else window.addEventListener("pywebviewready", load);
