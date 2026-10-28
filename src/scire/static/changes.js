const cache = new Map();
export async function changesView(container, session, api, escape) {
  const key = session.repo + "/" + session.id + "/" + session.review.head;
  container.innerHTML = '<p class="table-empty">Loading pinned changes…</p>';
  try {
    let value = cache.get(key);
    if (!value) {
      value = await api(`sessions/${session.repo}/${session.id}/changes`);
      cache.set(key, value);
    }
    if (!container.isConnected) return;
    const additions = value.files.reduce((n, f) => n + f.additions, 0),
      deletions = value.files.reduce((n, f) => n + f.deletions, 0);
    container.innerHTML = `<div class="changes-summary"><span>${value.files.length} changed files</span><span class="diff-count"><b>+${additions}</b> <em>−${deletions}</em></span><code>${escape(value.base.slice(0, 8))} → ${escape(value.head.slice(0, 8))}</code></div><div class="changes-files">${value.files.map((f) => `<details class="diff-file" open><summary><strong>${escape(f.path)}</strong><span>+${f.additions} −${f.deletions}</span></summary><div class="diff-scroll">${f.hunks.map((h) => `<div class="diff-hunk"><div class="diff-hunk-header">${escape(h.header)}</div>${h.lines.map((l) => `<div class="diff-line ${l.kind}"><span class="diff-line-number">${l.old ?? ""}</span><span class="diff-line-number">${l.new ?? ""}</span><span class="diff-sign">${l.kind === "add" ? "+" : l.kind === "remove" ? "−" : " "}</span><code>${escape(l.text) || " "}</code></div>`).join("")}</div>`).join("") || '<p class="table-empty">No text hunks available.</p>'}</div></details>`).join("") || '<p class="table-empty">No eligible text changes in this revision.</p>'}</div>`;
  } catch (e) {
    if (container.isConnected) container.textContent = e.message;
  }
}
