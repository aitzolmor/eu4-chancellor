// Trend charts for the panel's Charts tab (D-045, D-048): small multiples of the campaign
// journal's numbers, drawn as plain SVG so the panel works offline without a library.
//
// One measure per chart (never two y-scales); income and expenses share one because they
// share a unit. Lines are 2px, gridlines hairline and recessive, text in text colours,
// a crosshair and tooltip on hover, and a table of the same numbers for every chart.
// Colours go in a fixed order: the player is always the first, the rivals follow.

const SVG = "http://www.w3.org/2000/svg";
const HEIGHT = 128;
const PAD = { top: 10, right: 12, bottom: 20, left: 44 };

// The player's own charts: a title and the journal keys of its series.
export const CHARTS = [
  { title: "Treasury (ducats)", keys: ["treasury"] },
  { title: "Income and expenses (a month)", keys: ["income", "expenses"] },
  { title: "Regiments", keys: ["regiments"] },
  { title: "Manpower (thousands)", keys: ["manpower"] },
  { title: "Development", keys: ["development"] },
  { title: "Countries at 50+ AE", keys: ["at_coalition_ae"] },
];
// The comparison charts (D-048): the player against up to three rivals.
export const COMPARE_CHARTS = [
  { title: "Development", key: "development" },
  { title: "Regiments", key: "regiments" },
  { title: "Monthly income", key: "income" },
];
// The dataviz reference palette's dark steps, validated on the panel's surface for every
// pair (lines cross). Only three hues pass that; a fourth country is a dashed neutral line,
// so it never relies on colour alone.
const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-other)"];
const DASHED = 3; // the index drawn dashed
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

// series: [{ label, values } | null], drawn in SERIES order; a null keeps its colour slot
// empty. A legend shows for two or more.
function lineChart(data, title, series, width) {
  const drawn = series.filter(Boolean);
  const figure = document.createElement("figure");
  figure.className = "chart";
  const caption = document.createElement("figcaption");
  caption.textContent = title;
  figure.append(caption);

  const values = drawn.flatMap((s) => s.values.filter((v) => v !== null && v !== undefined));
  if (values.length < 2) {
    const note = document.createElement("p");
    note.className = "quiet";
    note.textContent = "Not enough saves recorded yet.";
    figure.append(note);
    return figure;
  }
  const svg = el("svg", { viewBox: `0 0 ${width} ${HEIGHT}`, role: "img", "aria-label": title });
  figure.append(svg);

  const years = data.years;
  const x0 = years[0];
  const x1 = years[years.length - 1] === x0 ? x0 + 1 : years[years.length - 1];
  const { low, high, step } = niceScale(Math.min(...values), Math.max(...values));
  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const x = (year) => PAD.left + ((year - x0) / (x1 - x0)) * plotW;
  const y = (value) => PAD.top + plotH - ((value - low) / (high - low || 1)) * plotH;
  const known = (value) => value !== null && value !== undefined;

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

  series.forEach((line, index) => {
    if (!line) return;
    // Gaps (a country not recorded on some saves) break the line instead of bridging it.
    let run = [];
    const flush = () => {
      if (run.length) {
        const attributes = { points: run.join(" "), class: "line", stroke: SERIES[index] };
        if (index === DASHED) attributes["stroke-dasharray"] = "5 4";
        el("polyline", attributes, svg);
      }
      run = [];
    };
    // A series marked `bridge` joins its known points across gaps: older saves keep the
    // other countries' numbers once a year only (D-048), which is thinning, not absence.
    line.values.forEach((value, i) => {
      if (known(value)) run.push(`${x(years[i])},${y(value)}`);
      else if (!line.bridge) flush();
    });
    flush();
  });

  // Hover: a crosshair at the nearest save, a dot on each line and a tooltip.
  const cross = el("line", { y1: PAD.top, y2: PAD.top + plotH, class: "cross", visibility: "hidden" }, svg);
  const dots = series.map((_, index) =>
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
    const parts = [data.dates[nearest]];
    series.forEach((line, index) => {
      if (!line) return;
      const value = line.values[nearest];
      dots[index].setAttribute("visibility", known(value) ? "visible" : "hidden");
      if (known(value)) {
        dots[index].setAttribute("cx", cx);
        dots[index].setAttribute("cy", y(value));
      }
      const label = drawn.length > 1 ? `${line.label}: ` : "";
      parts.push(`${label}${known(value) ? number.format(value) : "?"}`);
    });
    tip.textContent = parts.join(" · ");
    tip.hidden = false;
    tip.style.left = `${Math.min(Math.max((cx / width) * 100, 15), 65)}%`;
  });
  hit.addEventListener("mouseleave", () => {
    cross.setAttribute("visibility", "hidden");
    dots.forEach((dot) => dot.setAttribute("visibility", "hidden"));
    tip.hidden = true;
  });

  if (drawn.length > 1) {
    const legend = document.createElement("p");
    legend.className = "legend";
    series.forEach((line, index) => {
      if (!line) return;
      const item = document.createElement("span");
      const swatch = document.createElement("span");
      swatch.className = index === DASHED ? "swatch dashed" : "swatch";
      swatch.style.background = index === DASHED ? "" : SERIES[index];
      if (index === DASHED) swatch.style.borderColor = SERIES[index];
      item.append(swatch, line.label);
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

function heading(text) {
  const title = document.createElement("h2");
  title.className = "section-title charts-heading";
  title.textContent = text;
  return title;
}

// "Compare with": the countries picked (each removable), or the rivals by default, and a
// list to add one (D-049). onChange receives the new list; an empty one means the rivals.
function comparePicker(picker, data) {
  const row = document.createElement("div");
  row.className = "compare-picker";
  const label = document.createElement("span");
  label.className = "quiet";
  label.textContent = "Compare with:";
  row.append(label);
  if (picker.picked.length) {
    for (const tag of picker.picked) {
      const chip = document.createElement("span");
      chip.className = "chip";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.title = "Remove";
      remove.setAttribute("aria-label", `Stop comparing with ${data.names[tag] ?? tag}`);
      remove.addEventListener("click", () => picker.onChange(picker.picked.filter((t) => t !== tag)));
      chip.append(data.names[tag] ?? tag, remove);
      row.append(chip);
    }
    const back = document.createElement("button");
    back.type = "button";
    back.className = "link";
    back.textContent = "Back to your rivals";
    back.addEventListener("click", () => picker.onChange([]));
    row.append(back);
  } else {
    const basis = document.createElement("span");
    basis.textContent = `your ${data.compare_basis}`;
    row.append(basis);
  }
  if (picker.picked.length < 3) {
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Add a country to compare with");
    select.append(new Option("Add a country…", ""));
    for (const option of picker.options) {
      if (!picker.picked.includes(option.tag)) select.append(new Option(option.name, option.tag));
    }
    select.addEventListener("change", () => {
      if (select.value) picker.onChange([...picker.picked, select.value]);
    });
    row.append(select);
  }
  return row;
}

export function renderCharts(container, data, picker = null) {
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
  for (const chart of CHARTS) {
    const series = chart.keys.map((key) => ({ label: LEGEND[key] ?? key, values: data.series[key] }));
    container.append(lineChart(data, chart.title, series, width));
  }

  const compare = data.compare ?? [];
  if (compare.some(Boolean) || picker) {
    const player = Object.keys(data.names)[0];
    container.append(heading(`You and the ${data.compare_basis}`));
    if (picker) container.append(comparePicker(picker, data));
    for (const chart of COMPARE_CHARTS) {
      // compare holds colour slots: an empty slot (null) keeps the others' colours put.
      const series = [
        { label: data.names[player], values: data.series[chart.key], bridge: true },
        ...compare.map((tag) =>
          tag ? { label: data.names[tag] ?? tag, values: data.others[tag][chart.key], bridge: true } : null,
        ),
      ];
      container.append(lineChart(data, chart.title, series, width));
    }
  }
  container.append(table(data));
}
