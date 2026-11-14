// A small Markdown renderer for the Chancellor's answers: headings, paragraphs, lists,
// tables, bold, italics and inline code. Everything is HTML-escaped first, so text from
// the model can never inject markup. Unknown syntax is shown as plain text.

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

function escape(text) {
  return text.replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

function inline(text) {
  return escape(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
}

function cells(line) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
}

const TABLE_RULE = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;

export function renderMarkdown(source) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6); // keep headings small in a panel
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1])) {
      const head = cells(line).map((c) => `<th>${inline(c)}</th>`).join("");
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        rows.push(`<tr>${cells(lines[i]).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`);
        i += 1;
      }
      html.push(`<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`);
      continue;
    }
    const bullet = /^\s*[-*]\s+/;
    const number = /^\s*\d+[.)]\s+/;
    if (bullet.test(line) || number.test(line)) {
      const ordered = number.test(line);
      const marker = ordered ? number : bullet;
      const items = [];
      while (i < lines.length && marker.test(lines[i])) {
        items.push(`<li>${inline(lines[i].replace(marker, ""))}</li>`);
        i += 1;
      }
      const tag = ordered ? "ol" : "ul";
      html.push(`<${tag}>${items.join("")}</${tag}>`);
      continue;
    }
    const paragraph = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^#{1,4}\s/.test(lines[i]) &&
      !bullet.test(lines[i]) &&
      !number.test(lines[i]) &&
      !(lines[i].includes("|") && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1]))
    ) {
      paragraph.push(inline(lines[i]));
      i += 1;
    }
    html.push(`<p>${paragraph.join("<br>")}</p>`);
  }
  return html.join("");
}
