const modes = new Map();
const reviewCache = new Map();
export function repoHome(
  container,
  { repo, sessions, escape, percent, ago, api, actions },
) {
  if (!repo) {
    container.innerHTML =
      '<section class="card"><h2>Connect a repository</h2><p>Run <code>scire setup</code> in your terminal to choose repositories.</p></section>';
    return;
  }
  const m = repo.map,
    ready = m.status === "ready",
    busy = ["working", "queued"].includes(m.status);
  const assessed = m.concepts.filter((c) => c.attempts > 0).length;
  const weight = m.concepts.reduce((n, c) => n + c.importance, 0);
  const mastery = weight
    ? m.concepts.reduce((n, c) => n + c.mastery * c.importance, 0) / weight
    : 0;
  const items = sessions
    .filter((s) => s.repo === repo.id)
    .sort(
      (a, b) =>
        Number(a.complete) - Number(b.complete) || b.updated_at - a.updated_at,
    );
  container.innerHTML = `<div class="repo-home" data-home-repo="${escape(repo.id)}"><div class="repo-home-cards"><section class="card mastery-card"><div class="card-heading"><h2>Concept mastery</h2><button class="text-button" id="home-concepts">View concept tree ↗</button></div><div class="mastery-overview"><strong>${assessed ? percent(mastery) + "<span>%</span>" : "—"}</strong><div><b>${assessed ? "Estimated understanding" : "Not assessed yet"}</b><small>${assessed} of ${m.concepts.length} concepts assessed</small></div></div><div class="home-areas">${m.areas
    .filter((a) => !a.parent)
    .slice(0, 4)
    .map(
      (a) =>
        `<div class="home-area"><span>${escape(a.name)}</span><div class="bar"><span style="width:${a.assessed_count ? percent(a.mastery) : 0}%"></span></div><small>${a.assessed_count ? percent(a.mastery) + "%" : "—"}</small></div>`,
    )
    .join(
      "",
    )}</div><div class="card-footer"><span>${m.areas.length} areas · ${m.concepts.length} concepts</span>${ready ? '<button class="primary" id="home-learn">Start learning →</button>' : `<button class="secondary" id="home-map">${busy ? "View mapping activity" : "Build codebase map →"}</button>`}</div></section><section class="card home-sessions"><div class="card-heading"><h2>Sessions</h2><span>${items.length}</span></div><div class="home-session-list">${
    items
      .slice(0, 6)
      .map(
        (s) =>
          `<a class="home-session" href="/w/${s.repo}/${s.id}/"><div class="session-type">${s.target === "learn" ? "Lesson" : "Review"}<span>${escape(s.status === "working" || s.status === "queued" ? "Preparing" : s.complete ? "Completed" : s.status === "error" ? "Needs retry" : "In progress")}</span></div><strong>${escape(s.title)}</strong><div class="session-detail"><span>${s.answered_count || 0}/${s.question_count || 0} questions · ${ago(s.updated_at)}</span><span>${s.complete ? "Revisit" : "Resume"} →</span></div></a>`,
      )
      .join("") ||
    '<div class="session-empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3"><path d="M5 4h14v16H5zM9 8h6M9 12h6M9 16h3"/></svg><p>Your lessons and reviews will appear here.</p><span>Your answers are saved as you go.</span></div>'
  }</div></section></div>${ready && !assessed && repo.onboarding?.calibration !== "skipped" && !items.some((s) => s.calibration) ? '<section class="repo-calibration"><div><h3>Find your starting point</h3><p>An optional two-minute calibration helps Scire choose what to explain.</p></div><div><button class="text-button" id="home-skip-calibration">Skip for now</button><button class="secondary" id="home-calibrate">Take calibration →</button></div></section>' : ""}${busy ? '<button class="mapping-banner" id="home-map-activity"><i class="pulse"></i>Mapping this repository · View live activity →</button>' : ""}${m.error ? `<div class="error">${escape(m.error)}</div>` : ""}<section class="card review-table-card"><div class="review-table-heading"><h2>Review a change</h2><div class="segmented" role="tablist" aria-label="Review targets"><button role="tab" data-review-mode="prs">Pull requests</button><button role="tab" data-review-mode="branches">Branches</button></div></div><div id="home-review-table"><p class="table-empty">Loading changes…</p></div></section></div>`;
  const get = (s) => container.querySelector(s);
  get("#home-concepts").onclick = actions.concepts;
  if (get("#home-learn")) get("#home-learn").onclick = actions.learn;
  if (get("#home-map"))
    get("#home-map").onclick = busy ? actions.activity : actions.build;
  if (get("#home-map-activity"))
    get("#home-map-activity").onclick = actions.activity;
  if (get("#home-calibrate"))
    get("#home-calibrate").onclick = actions.calibrate;
  if (get("#home-skip-calibration"))
    get("#home-skip-calibration").onclick = actions.skipCalibration;
  function table(value) {
    if (
      !get("#home-review-table") ||
      get(".repo-home")?.dataset.homeRepo !== repo.id
    )
      return;
    const mode = modes.get(repo.id) || "prs";
    container.querySelectorAll("[data-review-mode]").forEach((b) => {
      b.setAttribute("aria-selected", String(b.dataset.reviewMode === mode));
      b.onclick = () => {
        modes.set(repo.id, b.dataset.reviewMode);
        table(value);
      };
    });
    const rows =
      mode === "prs" ? value.items : value.branches.map((name) => ({ name }));
    get("#home-review-table").innerHTML = rows.length
      ? `<div class="review-table-scroll"><table class="review-table"><thead><tr><th>${mode === "prs" ? "Pull request" : "Branch"}</th><th>${mode === "prs" ? "Updated" : "Compare"}</th><th>Status</th><th><span class="sr-only">Action</span></th></tr></thead><tbody>${rows.map((row) => `<tr><td><strong>${escape(row.title || row.name)}</strong><small>${mode === "prs" ? "#" + row.number : "Local branch"}</small></td><td>${mode === "prs" ? ago(Date.parse(row.updatedAt) / 1000) : "Default branch"}</td><td>${row.waiting ? '<span class="pill blue">Waiting on you</span>' : '<span class="quiet">' + (mode === "prs" ? "Open" : "Available") + "</span>"}</td><td><button class="secondary" data-review-target="${escape(mode === "prs" ? row.number : row.name)}" aria-label="Review ${escape(mode === "prs" ? "#" + row.number : row.name)}">Review →</button></td></tr>`).join("")}</tbody></table></div>`
      : `<div class="table-empty">${escape(mode === "prs" ? value.error || "No open pull requests. Switch to branches to review local work." : "No local branches found.")}</div>`;
    if (mode === "branches")
      get("#home-review-table").insertAdjacentHTML(
        "beforeend",
        '<form class="range-review"><label class="sr-only" for="review-range">Revision range</label><input id="review-range" placeholder="Or enter a revision range, e.g. main..feature"><button class="secondary">Review range →</button></form>',
      );
    container
      .querySelectorAll("[data-review-target]")
      .forEach(
        (b) => (b.onclick = () => actions.review(b.dataset.reviewTarget)),
      );
    const form = get(".range-review");
    if (form)
      form.onsubmit = (e) => {
        e.preventDefault();
        const target = get("#review-range").value.trim();
        if (target) actions.review(target);
      };
  }
  const cached = reviewCache.get(repo.id);
  if (cached) table(cached);
  api("reviews/" + repo.id)
    .then((value) => {
      reviewCache.set(repo.id, value);
      if (
        container.querySelector(".repo-home") &&
        get("#home-concepts")?.onclick === actions.concepts
      )
        table(value);
    })
    .catch((e) => table({ items: [], branches: [], error: e.message }));
}
