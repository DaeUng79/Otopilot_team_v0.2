// Chat answers are untrusted text. Escape raw HTML and emit only the tags below.
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));

function inline(source, citation) {
  const tokens = [];
  const stash = (html) => `\uE000${tokens.push(html) - 1}\uE001`;
  let text = String(source);
  text = text.replace(/`([^`\n]+)`/g, (_, code) => stash(`<code>${escapeHtml(code)}</code>`));
  text = text.replace(/\[(\d{1,4})(?:\s*[~\-–]\s*\d{1,4})?쪽\]/g,
    (label, page) => stash(citation ? citation(Number(page), label) : escapeHtml(label)));
  text = text.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) =>
    stash(`<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`));
  let html = escapeHtml(text);
  html = html.replace(/\*\*([^*\n]+)\*\*|__([^_\n]+)__/g, (_, a, b) => `<strong>${a || b}</strong>`);
  html = html.replace(/\*([^*\n]+)\*|_([^_\n]+)_/g, (_, a, b) => `<em>${a || b}</em>`);
  html = html.replace(/~~([^~\n]+)~~/g, (_, value) => `<del>${value}</del>`);
  return html.replace(/\uE000(\d+)\uE001/g, (_, index) => tokens[Number(index)]);
}

const fence = (line) => /^\s*```/.test(line);
const heading = (line) => /^\s{0,3}#{1,6}\s+/.test(line);
const item = (line) => /^\s{0,3}(?:[-*+]|\d+[.)])\s+/.test(line);
const quote = (line) => /^\s{0,3}>\s?/.test(line);
const rule = (line) => /^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$/.test(line);
const tableDivider = (line) => /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
const cells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
const blockStart = (line) => fence(line) || heading(line) || item(line) || quote(line) || rule(line);

export function renderAnswerMarkdown(value, { citation } = {}) {
  const lines = String(value ?? '').replace(/\r\n?/g, '\n').split('\n');
  const output = [];
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (fence(line)) {
      const code = [];
      i++;
      while (i < lines.length && !fence(lines[i])) code.push(lines[i++]);
      if (i < lines.length) i++;
      output.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`);
      continue;
    }
    if (i + 1 < lines.length && line.includes('|') && tableDivider(lines[i + 1])) {
      const headers = cells(line); i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) rows.push(cells(lines[i++]));
      output.push(`<div class="evc-table-wrap"><table><thead><tr>${headers.map((cell) => `<th>${inline(cell, citation)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_, n) => `<td>${inline(row[n] || '', citation)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
      continue;
    }
    if (rule(line)) { output.push('<hr>'); i++; continue; }
    if (heading(line)) { output.push(`<h5>${inline(line.replace(/^\s{0,3}#{1,6}\s+/, ''), citation)}</h5>`); i++; continue; }
    if (item(line)) {
      const ordered = /^\s{0,3}\d+[.)]\s+/.test(line), tag = ordered ? 'ol' : 'ul', rows = [];
      while (i < lines.length && item(lines[i]) && /^\s{0,3}\d+[.)]\s+/.test(lines[i]) === ordered) {
        rows.push(`<li>${inline(lines[i].replace(/^\s{0,3}(?:[-*+]|\d+[.)])\s+/, ''), citation)}</li>`);
        i++;
      }
      output.push(`<${tag}>${rows.join('')}</${tag}>`);
      continue;
    }
    if (quote(line)) {
      const rows = [];
      while (i < lines.length && quote(lines[i])) rows.push(inline(lines[i++].replace(/^\s{0,3}>\s?/, ''), citation));
      output.push(`<blockquote>${rows.join('<br>')}</blockquote>`);
      continue;
    }
    const paragraph = [line]; i++;
    while (i < lines.length && lines[i].trim() && !blockStart(lines[i]) && !(i + 1 < lines.length && lines[i].includes('|') && tableDivider(lines[i + 1]))) paragraph.push(lines[i++]);
    output.push(`<p>${paragraph.map((part) => inline(part, citation)).join('<br>')}</p>`);
  }
  return output.join('');
}
