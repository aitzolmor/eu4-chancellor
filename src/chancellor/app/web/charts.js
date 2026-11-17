// Trend charts for the panel's Charts tab (D-045): small multiples of the campaign
// journal's numbers, drawn as plain SVG so the panel works offline without a library.
//
// One measure per chart (never two y-scales); income and expenses share one because they
// share a unit. Lines are 2px, gridlines hairline and recessive, text in text colours,
// a crosshair and tooltip on hover, and a table of the same numbers for every chart.

const SVG = "http://www.w3.org/2000/svg";
const HEIGHT = 128;
const PAD = { top: 10, right: 12, bottom: 20, left: 44 };

// What each chart shows: its title and series (journal keys), in fixed colour order.
export const CHARTS = [
  { title: "Treasury (ducats)", keys: ["treasury"] },
  { title: "Income and expenses (a month)", keys: ["income", "expenses"] },
  { title: "Regiments", keys: ["regiments"] },
  { title: "Manpower (thousands)", keys: ["manpower"] },
  { title: "Development", keys: ["development"] },
  { title: "Countries at 50+ AE", keys: ["at_coalition_ae"] },
];
const SERIES = ["var(--series-1)", "var(--series-2)"];
const LEGEND = { income: "income", expenses: "expenses" };

const number = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });

function el(name, attributes = {}, parent = null) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (parent) parent.append(node);
  return node;
}

// Round the axis to readable steps: about three gridlines from 0 (or the minimum) up.
function niceScale(min, max) {
  const low = Math.min(0, min);
  const span = Math.max(max - low, 1);
  const raw = span / 3;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw);
  return { low: Math.floor(low / step) * step, high: Math.ceil(max / step) * step, step };
}

function lineChart(data, chart, width) {
  const figure = document.createElement("figure");
  figure.className = "chart";
  const caption = document.createElement("figcaption");
  caption.textContent = chart.title;
  figure.append(caption);

  const values = chart.keys.flatMap((k) => data.series[k].filter((v) => v !== null));
  const svg = el("svg", { viewBox: `0 0 ${width} ${HEIGHT}`, role: "img", "aria-label": chart.title });
  figure.append(svg);
  if (values.length < 2) {
    const note = document.createElement("p");
    note.className = "quiet";
    note.textContent = "Not enough saves recorded yet.";
    figure.append(note);
    svg.remove();
    return figure;
  }

  const years = data.years;
  const x0 = years[0];
  const x1 = years[years.length - 1] === x0 ? x0 + 1 : years[years.length - 1];
  const { low, high, step } = niceScale(Math.min(...values), Math.max(...values));
  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const x = (year) => PAD.left + ((year - x0) / (x1 - x0)) * plotW;
  const y = (value) => PAD.top + plotH - ((value - low) / (high - low || 1)) * plotH;

  for (let tick = low; tick <= high + step / 2; tick += step) {
    el("line", { x1: PAD.left, x2: width - PAD.right, y1: y(tick), y2: y(tick), class: "grid" }, svg);
    el("text", { x: PAD.left - 6, y: y(tick) + 4, class: "tick", "text-anchor": "end" }, svg).textContent =
      number.format(tick);
  }
  for (const year of [x0, Math.round((x0 + x1) / 2), x1]) {
    el("text", { x: x(year), y: HEIGHT - 4, class: "tick", "text-anchor": "middle" }, svg).textContent =
      String(Math.floor(year));
  }
  // The journal's main events (wars, rulers, provinces) as small ticks on the time axis.
  for (const event of data.events) {
    const mark = el("circle", { cx: x(event.year), cy: PAD.top + plotH + 1, r: 2.5, class: "event" }, svg);
    el("title", {}, mark).textContent = `${event.date}: ${event.text}`;
  }

  chart.keys.forEach((key, index) => {
    const points = data.series[key]
      .map((value, i) => (value === null ? null : `${x(years[i])},${y(value)}`))
      .filter(Boolean);
    el("polyline", { points: points.join(" "), class: "line", stroke: SERIES[index] }, svg);
  });

  // Hover: a crosshair at the nearest save, a dot on each line and a tooltip.
  const cross = el("line", { y1: PAD.top, y2: PAD.top + plotH, class: "cross", visibility: "hidden" }, svg);
  const dots = chart.keys.map((_, index) =>
    el("circle", { r: 4, class: "dot", fill: SERIES[index], visibility: "hidden" }, svg),
  );
  const tip = document.createElement("div");
  tip.className = "tip";
  tip.hidden = true;
  figure.append(tip);
  const hit = el("rect", { x: PAD.left, y: PAD.top, width: plotW, height: plotH, class: "hit" }, svg);
  hit.addEventListener("mousemove", (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * width;
    let nearest = 0;
    years.forEach((year, i) => {
      if (Math.abs(x(year) - px) < Math.abs(x(years[nearest]) - px)) nearest = i;
    });
    const cx = x(years[nearest]);
    cross.setAttribute("x1", cx);
    cross.setAttribute("x2", cx);
    cross.setAttribute("visibility", "visible");
    const lines = [data.dates[nearest]];
    chart.keys.forEach((key, index) => {
      const value = data.series[key][nearest];
      dots[index].setAttribute("visibility", value === null ? "hidden" : "visible");
      if (value !== null) {
        dots[index].setAttribute("cx", cx);
        dots[index].setAttribute("cy", y(value));
      }
      const label = chart.keys.length > 1 ? `${LEGEND[key] ?? key}: ` : "";
      lines.push(`${label}${value === null ? "?" : number.format(value)}`);
    });
    tip.textContent = lines.join(" · ");
    tip.hidden = false;
    tip.style.left = `${Math.min(Math.max((cx / width) * 100, 10), 70)}%`;
  });
  hit.addEventListener("mouseleave", () => {
    cross.setAttribute("visibility", "hidden");
    dots.forEach((dot) => dot.setAttribute("visibility", "hidden"));
    tip.hidden = true;
  });

  if (chart.keys.length > 1) {
    const legend = document.createElement("p");
    legend.className = "legend";
    chart.keys.forEach((key, index) => {
      const item = document.createElement("span");
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = SERIES[index];
      item.append(swatch, LEGEND[key] ?? key);
      legend.append(item);
    });
    figure.append(legend);
  }
  return figure;
}

function table(data) {
  const details = document.createElement("details");
  details.className = "chart-table";
  const summary = document.createElement("summary");
  summary.textContent = "Show the numbers as a table";
  const grid = document.createElement("table");
  const keys = CHARTS.flatMap((c) => c.keys);
  const head = grid.createTHead().insertRow();
  for (const text of ["Date", ...keys.map((k) => data.labels[k] ?? k)]) {
    const cell = document.createElement("th");
    cell.textContent = text;
    head.append(cell);
  }
  const body = grid.createTBody();
  data.dates.forEach((date, i) => {
    const row = body.insertRow();
    row.insertCell().textContent = date;
    for (const key of keys) {
      const value = data.series[key][i];
      row.insertCell().textContent = value === null ? "-" : number.format(value);
    }
  });
  details.append(summary, grid);
  return details;
}

export function renderCharts(container, data) {
  container.replaceChildren();
  const width = Math.max(container.clientWidth || 320, 240);
  if (!data.dates.length) {
    const note = document.createElement("p");
    note.className = "quiet";
    note.textContent =
      "No saves recorded yet. Each save the Chancellor reads is added to the campaign journal; " +
      "`chancellor journal --backfill` can add older ones.";
    container.append(note);
    return;
  }
  const intro = document.createElement("p");
  intro.className = "quiet";
  intro.textContent =
    `${data.dates.length} saves, ${data.dates[0]} to ${data.dates[data.dates.length - 1]}. ` +
    "Dots on the time axis mark wars, rulers and provinces; hover them.";
  container.append(intro);
  for (const chart of CHARTS) container.append(lineChart(data, chart, width));
  container.append(table(data));
}
