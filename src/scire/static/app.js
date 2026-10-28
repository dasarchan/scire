const token =
  location.hash.slice(1) || sessionStorage.getItem("scire-token") || "";
if (token) {
  sessionStorage.setItem("scire-token", token);
  history.replaceState(null, "", location.pathname + location.search);
}
const main = document.querySelector("#main"),
  content = document.querySelector("#content"),
  modal = document.querySelector("#modal");
let state,
  selectedRepo = null,
  view = "home",
  workspace = null,
  activeModule = null,
  pinned = false,
  anchor = null,
  keyword = "",
  keywordIndex = 0,
  lastSignature = "",
  polling = false,
  editing = false,
  headChecked = 0;
const path = location.pathname.match(/^\/w\/([a-z0-9]+)\/([a-z0-9]+)\/$/);
if (path) {
  selectedRepo = path[1];
  view = "session";
}
const escape = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const percent = (n) => Math.round((n || 0) * 100),
  ago = (t) => {
    const m = Math.floor((Date.now() / 1000 - t) / 60);
    return m < 1
      ? "just now"
      : m < 60
        ? m + "m ago"
        : m < 1440
          ? Math.floor(m / 60) + "h ago"
          : Math.floor(m / 1440) + "d ago";
  };
const mdCache = new Map();
async function api(path, body) {
  const r = await fetch("/api/" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "x-scire-token": token, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let result;
  try {
    result = await r.json();
  } catch {
    throw Error(
      "The local server did not return a response. Check your Scire terminal.",
    );
  }
  if (!r.ok)
    throw Error(
      result.error || JSON.stringify(result.detail) || "Request failed",
    );
  return result;
}
function toast(message) {
  const node = document.querySelector("#toast");
  node.textContent = message;
  node.hidden = false;
  setTimeout(() => (node.hidden = true), 6500);
}
function areaBar(a) {
  return `<div class="area"><div class="area-top"><span>${escape(a.name)}</span><span>${percent(a.mastery)}%</span></div><div class="bar"><span style="width:${percent(a.mastery)}%"></span></div></div>`;
}
function setHeading(
  title,
  subtitle,
  eyebrow = "YOUR UNDERSTANDING, UP TO DATE",
) {
  main.querySelector(":scope > h1").textContent = title;
  main.querySelector(":scope > .subtitle").textContent = subtitle;
  main.querySelector(":scope > .eyebrow").textContent = eyebrow;
}
function currentAnchors() {
  return workspace?.modules.find((m) => m.id === activeModule)?.resolved || {};
}
function referenceText(text) {
  const refs = currentAnchors();
  return text.replace(/\[([a-z0-9_, -]+)\](?!\()/g, (match, group) => {
    const ids = group.split(",").map((x) => x.trim());
    if (!ids.every((id) => refs[id])) return match;
    return ids
      .map(
        (id) =>
          `[${refs[id].path.split("/").at(-1)}:${refs[id].start_line}](#scire:${id})`,
      )
      .join(" ");
  });
}
function inlineReferences(text) {
  const refs = currentAnchors();
  return escape(text).replace(/\[([a-z0-9_, -]+)\]/g, (match, group) => {
    const ids = group.split(",").map((x) => x.trim());
    if (!ids.every((id) => refs[id])) return match;
    return ids
      .map(
        (id) =>
          `<button class="inline-reference" data-anchor="${escape(id)}">${escape(refs[id].path.split("/").at(-1))}:${refs[id].start_line}</button>`,
      )
      .join(" ");
  });
}
function markdown(text) {
  text = referenceText(text);
  const key = "md-" + Math.random().toString(36).slice(2);
  queueMicrotask(async () => {
    const node = document.getElementById(key);
    if (!node) return;
    try {
      let promise = mdCache.get(text);
      if (!promise) {
        promise = api("render", { text }).then((r) => r.html);
        mdCache.set(text, promise);
      }
      const html = await promise;
      if (node.isConnected) {
        node.innerHTML = html;
        node.querySelectorAll('a[href^="#scire:"]').forEach(
          (link) =>
            (link.onclick = (e) => {
              e.preventDefault();
              const ref = currentAnchors()[link.getAttribute("href").slice(7)];
              if (ref) {
                anchor = ref;
                pinned = true;
                keyword = "";
                renderCode();
              }
            }),
        );
      }
    } catch {
      if (node.isConnected) node.textContent = text;
    }
  });
  return `<div class="prose" id="${key}"></div>`;
}
function autosize() {
  document.querySelectorAll("textarea").forEach((t) => {
    const grow = () => {
      t.style.height = "auto";
      t.style.height = Math.min(500, t.scrollHeight) + "px";
    };
    t.addEventListener("input", grow);
    grow();
  });
}
function setup() {
  setHeading(
    "Make this your workspace.",
    "A few details, then the code.",
    "WELCOME TO SCIRE",
  );
  content.innerHTML = `<section class="card setup"><h2>A small introduction</h2><p>Choose the code you work with and tell Scire about your experience.</p><form id="setup-form"><label>Your name</label><input name="name" required placeholder="Alex" value="${escape(state.profile.name)}"><label>What do you work on?</label><textarea name="role" placeholder="Backend engineer, new to this repository…">${escape(state.profile.role)}</textarea><label>Repository paths — one per line</label><textarea name="paths" required placeholder="/Users/you/work/project">${escape(state.repos.map((r) => r.path).join("\n"))}</textarea><label>OpenCode model</label><input name="model" required list="models" placeholder="provider/model" value="${escape(state.profile.model)}"><datalist id="models"></datalist><label>Fast triage model (optional)</label><input name="cheap_model" list="models" placeholder="Defaults to your primary model" value="${escape(state.profile.cheap_model)}"><p><small>OpenCode handles provider login. To connect an account, run <code>scire setup --connect</code> in your terminal. Keys never go in this form.</small></p><label style="display:flex;gap:10px;align-items:center"><input type="checkbox" name="map_now" checked style="width:auto">Build repository maps in the background</label><button class="primary">Create workspace →</button></form></section>`;
  api("models")
    .then((r) => {
      const n = document.querySelector("#models");
      if (n)
        n.innerHTML = r.models
          .map((m) => `<option value="${escape(m)}">`)
          .join("");
    })
    .catch(() => {});
  document.querySelector("#setup-form").onsubmit = async (e) => {
    e.preventDefault();
    const button = e.target.querySelector("button");
    button.disabled = true;
    const d = Object.fromEntries(new FormData(e.target));
    d.paths = d.paths
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
    d.map_now = d.map_now === "on";
    try {
      await api("setup", d);
      view = "home";
      await refresh();
    } catch (e) {
      toast(e.message);
      button.disabled = false;
    }
  };
  autosize();
}
function areaTree(map, learnButton = true, parent = null) {
  return map.areas
    .filter((a) => (a.parent ?? null) === parent)
    .map(
      (a) =>
        `<details><summary><span>${escape(a.name)}</span><span class="bar"><span style="width:${percent(a.mastery)}%"></span></span><small>${percent(a.mastery)}%</small></summary><p>${escape(a.summary)}</p>${areaTree(map, learnButton, a.id)}${map.concepts
          .filter((c) => c.parent === a.id)
          .map(
            (c) =>
              `<div class="concept-leaf"><div><b>${escape(c.name)}</b><p>${percent(c.mastery)}% estimated · ${c.attempts} observations${c.code_changed ? " · code changed" : ""}</p></div>${learnButton ? `<button class="secondary" data-focus="${escape(c.id)}">Learn this →</button>` : ""}</div>`,
          )
          .join("")}</details>`,
    )
    .join("");
}
function chooseRepo(callback) {
  if (selectedRepo) {
    callback(selectedRepo);
    return;
  }
  if (state.repos.length === 1) {
    callback(state.repos[0].id);
    return;
  }
  modal.innerHTML = `<h2>Choose a repository</h2>${state.repos.map((r) => `<div class="row"><button data-choice="${r.id}">${escape(r.name)}</button></div>`).join("")}<div class="dialog-actions"><button class="secondary" data-close>Cancel</button></div>`;
  modal.showModal();
  modal.querySelectorAll("[data-choice]").forEach(
    (b) =>
      (b.onclick = () => {
        modal.close();
        callback(b.dataset.choice);
      }),
  );
  modal.querySelector("[data-close]").onclick = () => modal.close();
}
async function openNew(rid, target = "learn", focus = null) {
  try {
    const result = await api("sessions", { repo: rid, target, focus });
    location.href = result.url;
  } catch (e) {
    toast(e.message);
  }
}
function conceptsDialog(rid) {
  const repo = state.repos.find((r) => r.id === rid);
  modal.innerHTML = `<p class="eyebrow">${escape(repo.name)}</p><h2>Choose an idea to explore</h2><div class="knowledge-tree">${areaTree(repo.map)}</div><div class="dialog-actions"><button class="secondary" data-close>Close</button></div>`;
  modal.showModal();
  modal.querySelector("[data-close]").onclick = () => modal.close();
  modal.querySelectorAll("[data-focus]").forEach(
    (b) =>
      (b.onclick = () => {
        modal.close();
        openNew(rid, "learn", b.dataset.focus);
      }),
  );
}
async function loadReviews(repos) {
  for (const repo of repos) {
    const node = document.querySelector(`[data-reviews="${repo.id}"]`);
    if (!node) continue;
    try {
      const value = await api("reviews/" + repo.id);
      if (!node.isConnected) return;
      node.innerHTML = value.items.length
        ? value.items
            .slice(0, 6)
            .map(
              (pr) =>
                `<button class="review-item" data-pr="${pr.number}"><span>#${pr.number} · ${escape(ago(Date.parse(pr.updatedAt) / 1000))}</span><b>${escape(pr.title)}</b>${pr.waiting ? '<span class="pill blue">Waiting on you</span>' : ""}</button>`,
            )
            .join("")
        : `<div class="empty"><p>${escape(value.error || "No open pull requests. Choose a local branch to review a change.")}</p></div>`;
      node
        .querySelectorAll("[data-pr]")
        .forEach((b) => (b.onclick = () => openNew(repo.id, b.dataset.pr)));
      node.dataset.branches = JSON.stringify(value.branches);
    } catch (e) {
      node.textContent = e.message;
    }
  }
}
function branchDialog() {
  chooseRepo(async (rid) => {
    try {
      const data = await api("reviews/" + rid);
      modal.innerHTML = `<h2>Review a local change</h2><p>Scire pins the code at its head commit. Your checkout is never changed.</p><label>Branch or revision range</label><input id="review-target" list="branches" placeholder="feature-branch or main...feature"><datalist id="branches">${data.branches.map((b) => `<option value="${escape(b)}">`).join("")}</datalist><div class="dialog-actions"><button class="secondary" data-close>Cancel</button><button class="primary" id="start-review">Prepare review →</button></div>`;
      modal.showModal();
      modal.querySelector("[data-close]").onclick = () => modal.close();
      document.querySelector("#start-review").onclick = () => {
        const target = document.querySelector("#review-target").value.trim();
        if (target) {
          modal.close();
          openNew(rid, target);
        }
      };
    } catch (e) {
      toast(e.message);
    }
  });
}
function askForm(session = null) {
  return `<form class="ask" id="ask-form"><textarea name="question" rows="1" placeholder="What would you like to understand?" aria-label="Ask about the codebase"></textarea><button class="primary">Explore question →</button></form><p class="ask-caption">${session ? "Your question stays as a topic in this session." : "A quick answer, a focused lesson, or a deeper round — depending on your question."}</p>`;
}
function bindAsk(session = null) {
  const form = document.querySelector("#ask-form");
  if (!form) return;
  form.onsubmit = (e) => {
    e.preventDefault();
    const question = form.elements.question.value.trim();
    if (!question) return;
    chooseRepo(async (rid) => {
      const button = form.querySelector("button");
      button.disabled = true;
      button.textContent = "Finding the right approach…";
      try {
        const result = await api("ask", { repo: rid, session, question });
        location.href = `/w/${rid}/${result.session}/`;
      } catch (e) {
        toast(e.message);
        button.disabled = false;
        button.textContent = "Explore question →";
      }
    });
  };
  autosize();
}
function render() {
  if (!state) return;
  document.querySelector("#profile-badge").textContent = (
    state.profile.name || "You"
  )
    .slice(0, 1)
    .toUpperCase();
  const repos = selectedRepo
    ? state.repos.filter((r) => r.id === selectedRepo)
    : state.repos;
  document.querySelector("#repo-menu").innerHTML =
    `${escape(selectedRepo ? repos[0]?.name : "All repositories")} <span>⌄</span>`;
  if (!state.profile.setup) {
    setup();
    return;
  }
  if (view === "session") {
    renderWorkspace();
    return;
  }
  document.querySelector("#session-nav").innerHTML = "";
  if (view === "knowledge") {
    setHeading(
      "What you know, and what to revisit.",
      "A provisional picture, shaped by your answers and changes in the code.",
      "KNOWLEDGE",
    );
    content.innerHTML = repos
      .map(
        (r) =>
          `<section class="card"><div class="card-heading"><h2>${escape(r.name)}</h2><span>${r.map.concepts.length} CONCEPTS</span></div><div class="knowledge-tree">${areaTree(r.map)}</div>${!r.map.areas.length ? "<p>The map is still being prepared.</p>" : ""}</section>`,
      )
      .join("");
    content
      .querySelectorAll("[data-focus]")
      .forEach(
        (b) =>
          (b.onclick = () =>
            openNew(
              selectedRepo ||
                state.repos.find((r) =>
                  r.map.concepts.some((c) => c.id === b.dataset.focus),
                ).id,
              "learn",
              b.dataset.focus,
            )),
      );
    return;
  }
  if (view === "settings") {
    setHeading(
      "Make Scire fit your work.",
      "Your profile and model preferences. Provider credentials remain in OpenCode.",
      "SETTINGS",
    );
    content.innerHTML = `<section class="card setup"><h2>Profile & models</h2><form id="settings-form"><label>Name</label><input name="name" value="${escape(state.profile.name)}"><label>Your experience</label><textarea name="role">${escape(state.profile.role)}</textarea><label>Primary model</label><input name="model" required value="${escape(state.profile.model)}"><label>Fast triage model (optional)</label><input name="cheap_model" value="${escape(state.profile.cheap_model)}"><p><small>Choose models available through your connected OpenCode providers. Triage uses this fast model when configured.</small></p><button class="primary">Save settings</button></form><div class="card-footer"><button class="secondary" id="add-repos">Add repositories</button><button class="secondary" id="quit-server">Quit Scire</button></div></section>`;
    document.querySelector("#settings-form").onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api("setup", Object.fromEntries(new FormData(e.target)));
        toast("Settings saved");
        await refresh();
      } catch (e) {
        toast(e.message);
      }
    };
    document.querySelector("#add-repos").onclick = setup;
    document.querySelector("#quit-server").onclick = async () => {
      await api("quit", {});
      toast("Scire is stopping. You can close this tab.");
    };
    autosize();
    return;
  }
  setHeading(
    "Keep the code in mind.",
    "Build a working model of your codebase. Make the next change with confidence.",
  );
  const sessions = state.sessions.filter(
    (s) => !selectedRepo || s.repo === selectedRepo,
  );
  content.innerHTML = `<div class="grid"><section class="card"><div class="card-heading"><h2>Learn</h2><span>BUILD YOUR MENTAL MODEL</span></div>${repos.map((r) => `<div><h3>${escape(r.name)} <span class="pill ${r.map.status === "ready" ? "blue" : ""}">${escape(r.map.status || "not mapped")}</span></h3><p><small>${r.map.concepts.length} mapped concepts${r.map.metrics ? ` · ${Math.round(r.map.metrics.seconds)}s · $${Number(r.map.metrics.cost).toFixed(3)} reported` : ""}</small></p>${r.map.areas.slice(0, 5).map(areaBar).join("") || '<div class="empty"><p>Your map organizes the code into areas you can learn one at a time.</p></div>'}${r.map.status === "working" ? `<div class="map-activity"><i class="pulse"></i>${escape(r.map.activity || "Exploring source…")}</div>` : ""}${r.map.error ? `<div class="error">${escape(r.map.error)}</div>` : ""}<div class="card-footer"><button class="secondary" data-concepts="${r.id}" ${!r.map.concepts.length ? "disabled" : ""}>View concepts</button>${r.map.status === "ready" ? `<button class="primary" data-learn="${r.id}">Start learning →</button>` : `<button class="${r.map.status === "working" ? "secondary" : "primary"}" data-map="${r.id}" ${r.map.status === "working" ? "disabled" : ""}>${r.map.status === "working" ? "Mapping…" : "Build map →"}</button>`}</div></div>`).join('<hr style="border:0;border-top:1px solid var(--line);margin:25px 0">') || '<p class="empty">Add a repository in setup to get started.</p>'}</section><section class="card"><div class="card-heading"><h2>Review</h2><span>UNDERSTAND THE CHANGE</span></div>${repos.map((r) => `<h3>${escape(r.name)}</h3><div data-reviews="${r.id}" class="review-list"><p class="quiet">Loading pull requests…</p></div>`).join("")}<div class="card-footer"><small>About 5 minutes in code you know.</small><button class="secondary" id="branch-review">Choose a branch ↗</button></div></section></div>${askForm()}<section class="card sessions"><div class="card-heading"><h2>Recent sessions</h2><span>CONTINUE WHERE YOU LEFT OFF</span></div>${
    sessions
      .slice(0, 10)
      .map(
        (s) =>
          `<div class="row"><div><h3>${escape(s.title)}</h3><p>${escape(state.repos.find((r) => r.id === s.repo)?.name)} · ${s.target === "learn" ? "Learning" : "Review"} · ${escape(s.status)} · ${ago(s.updated_at)}</p></div><button class="secondary" data-session="${s.repo}/${s.id}">Continue →</button></div>`,
      )
      .join("") ||
    '<div class="empty">Your first learning session starts here.</div>'
  }</section>`;
  content
    .querySelectorAll("[data-learn]")
    .forEach((b) => (b.onclick = () => openNew(b.dataset.learn)));
  content
    .querySelectorAll("[data-concepts]")
    .forEach((b) => (b.onclick = () => conceptsDialog(b.dataset.concepts)));
  content.querySelectorAll("[data-map]").forEach(
    (b) =>
      (b.onclick = async () => {
        try {
          b.disabled = true;
          await api(`maps/${b.dataset.map}/build`, {});
          await refresh();
        } catch (e) {
          toast(e.message);
        }
      }),
  );
  content
    .querySelectorAll("[data-session]")
    .forEach(
      (b) =>
        (b.onclick = () => (location.href = "/w/" + b.dataset.session + "/")),
    );
  document.querySelector("#branch-review").onclick = branchDialog;
  bindAsk();
  loadReviews(repos);
}
function renderDepth() {
  const s = workspace;
  content.innerHTML = `${s.topics
    .filter((t) => t.answer)
    .map(
      (t) =>
        `<section class="topic-answer"><h3>${escape(t.question)}</h3>${markdown(t.answer)}</section>`,
    )
    .join(
      "",
    )}<section class="card depth-form"><p class="eyebrow">BEFORE WE BEGIN</p><h2>Choose how deep to go.</h2><p>Skip areas you do not need, skim familiar ones, or take a deeper look. Your answers will refine the learning plan.</p><form id="depth-form"><div class="depth-list">${s.map.areas
    .map(
      (a) =>
        `<div class="row"><div><h3>${escape(a.name)}</h3><p>${escape(a.summary)}</p><small>${percent(a.mastery)}% estimated understanding</small></div><select name="${escape(a.id)}" aria-label="Depth for ${escape(a.name)}">${["skip", "skim", "standard", "deep"].map((d) => `<option value="${d}" ${(s.depths[a.id] || "standard") === d ? "selected" : ""}>${d[0].toUpperCase() + d.slice(1)}</option>`).join("")}</select></div>`,
    )
    .join(
      "",
    )}</div><div class="card-footer"><small>Start small. You can go deeper later.</small><button class="primary">${s.review ? "Prepare review" : "Start learning"} →</button></div></form></section>`;
  document.querySelector("#depth-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const depths = Object.fromEntries(new FormData(e.target));
      for (const a of s.map.areas)
        if (a.parent && !depths[a.id])
          depths[a.id] = depths[a.parent] || "standard";
      await api(`sessions/${s.repo}/${s.id}/start`, {
        depths,
        focus: s.pending_focus || s.focus,
      });
      await pollWorkspace(true);
    } catch (e) {
      toast(e.message);
    }
  };
}
function renderDiagram(value) {
  if (!value?.nodes?.length) return "";
  const nodes = value.nodes,
    w = 540,
    h = nodes.length * 85 + 25;
  const positions = Object.fromEntries(
    nodes.map((n, i) => [n.id, { x: 270, y: 45 + i * 85 }]),
  );
  return `<div class="diagram-box"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Flow diagram"><defs><marker id="arrow-${escape(activeModule)}" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#697c96"/></marker></defs>${value.edges
    .map((e) => {
      const a = positions[e.from],
        b = positions[e.to];
      return `<path d="M${a.x},${a.y + 20} L${b.x},${b.y - 22}" fill="none" stroke="#697c96" marker-end="url(#arrow-${escape(activeModule)})"/>${e.label ? `<text x="${a.x + 15}" y="${(a.y + b.y) / 2}" fill="#919aa9" font-size="10">${escape(e.label)}</text>` : ""}`;
    })
    .join("")}${nodes
    .map((n) => {
      const p = positions[n.id];
      return `<rect x="${p.x - 125}" y="${p.y - 22}" width="250" height="44" rx="5" fill="#1b2432" stroke="#465e80"/><text x="${p.x}" y="${p.y + 4}" text-anchor="middle" fill="#d8e3f5" font-size="12">${escape(n.label.slice(0, 40))}</text>`;
    })
    .join("")}</svg></div>`;
}
function renderQuestion(q, i) {
  const result = workspace.answers[q.key];
  return `<section class="question-card" data-question="${escape(q.key)}"><div class="question-meta"><span>QUESTION ${i + 1}</span><button data-anchor="${escape(q.ref)}">Inspect supporting code ↗</button></div><h3>${escape(q.question)}</h3>${q.options.map((o, n) => `<button class="option ${o.key === "unknown" ? "unknown" : ""} ${result && o.key === result.correct_option ? "correct" : ""} ${result && o.key === result.choice && !result.correct ? "incorrect" : ""}" data-answer="${escape(q.key)}" data-choice="${o.key}" ${result ? "disabled" : ""}>${n < 4 ? `<span>${String.fromCharCode(65 + n)}</span>` : "<span>?</span>"}${escape(o.text)}</button>`).join("")}${result ? `<div class="feedback"><b>${result.correct ? "That follows from the code." : result.choice === "unknown" ? "A useful gap to find." : "Here’s the missing connection."}</b>${markdown(result.explanation)}</div>` : ""}</section>`;
}
function renderFinding(f, module) {
  const draft = workspace.drafts?.[f.key] || {
    stance: "unsure",
    body: f.draft,
  };
  return `<section class="finding" data-finding="${escape(f.key)}"><div class="card-heading"><h3>${escape(f.title)}</h3><span class="pill">${escape(f.severity)}</span></div><div class="finding-label">FAILURE SCENARIO</div><p>${escape(f.scenario)}</p><div class="finding-label">EVIDENCE & IMPACT</div><p>${escape(f.evidence)}</p><p>${escape(f.impact)}</p><button class="secondary" data-anchor="${escape(f.ref)}">Inspect evidence ↗</button><div class="stance">${["agree", "unsure", "disagree"].map((x) => `<button class="${draft.stance === x ? "active" : ""}" data-stance="${x}" data-fid="${escape(f.key)}">${x[0].toUpperCase() + x.slice(1)}</button>`).join("")}</div><label>Comment draft — editable, not posted</label><textarea data-draft="${escape(f.key)}">${escape(draft.body)}</textarea><div class="card-footer"><small>${workspace.posted?.[f.key] ? "Posted to GitHub" : "Nothing leaves Scire until you explicitly post."}</small><button class="secondary" data-preview="${escape(f.key)}">Preview exact comment →</button></div></section>`;
}
function renderWorkspace() {
  if (!workspace) {
    content.innerHTML =
      '<div class="activity-card"><p>Opening your session…</p></div>';
    return;
  }
  const s = workspace;
  setHeading(
    s.title,
    s.review
      ? `Pinned at ${s.review.head.slice(0, 10)} · Review at your own pace.`
      : "A short explanation, the code behind it, and a few questions.",
    "WORKSPACE / " +
      (
        state.repos.find((r) => r.id === s.repo)?.name || "REPOSITORY"
      ).toUpperCase(),
  );
  if (!s.started_learning) {
    renderDepth();
    return;
  }
  const modules = s.modules.sort(
    (a, b) => a.round - b.round || a.index - b.index,
  );
  if (!activeModule || !modules.some((m) => m.id === activeModule))
    activeModule =
      modules.find((m) => m.status === "ready" && m.round === s.round)?.id ||
      modules.at(-1)?.id;
  const current = modules.find((m) => m.id === activeModule);
  document.querySelector("#session-nav").innerHTML =
    `<div class="nav-label">THIS SESSION</div>${modules.map((m) => `<button class="${m.id === activeModule ? "active" : ""}" data-module="${escape(m.id)}"><small>${m.status === "ready" && m.questions.every((q) => s.answers[q.key]) ? "✓" : String((m.index || 0) + 1).padStart(2, "0")}</small>${escape(m.title)}${m.status === "preview" ? " · preparing" : ""}</button>`).join("")}`;
  document.querySelectorAll("[data-module]").forEach(
    (b) =>
      (b.onclick = () => {
        activeModule = b.dataset.module;
        if (!pinned) anchor = null;
        renderWorkspace();
      }),
  );
  const banner = s.head_moved
    ? '<div class="head-banner">The PR head has changed. You are reading the pinned revision; refresh the review before posting comments.</div>'
    : "";
  const activity =
    s.status === "working" || s.status === "queued"
      ? `<div class="activity-card"><p><i class="pulse"></i>${escape(s.status === "queued" ? "Queued" : "OpenCode is working")} · ${Math.max(0, Math.floor(Date.now() / 1000 - (s.round_started_at || Date.now() / 1000)))}s elapsed</p>${s.activity
          .slice(-4)
          .map((a) => `<p>${escape(a.text)}</p>`)
          .join(
            "",
          )}<button class="secondary" id="cancel-round">Stop this run</button></div>`
      : "";
  let body = "";
  if (current?.status === "ready") {
    body = `<div class="module-title"><h2>${escape(current.title)}</h2><span class="pill">ROUND ${current.round}</span></div><div class="module-summary">${markdown(current.summary)}</div><section class="lesson-section"><h3>Why it exists</h3>${markdown(current.why)}</section><section class="lesson-section"><h3>Follow the flow</h3><ol>${current.flow.map((x) => `<li>${inlineReferences(x)}</li>`).join("")}</ol></section>${renderDiagram(current.diagram)}<section class="lesson-section"><h3>The key code</h3>${markdown(current.key_code)}<div class="anchor-links">${current.anchors.map((a) => `<button data-anchor="${escape(a.id)}">${escape(a.path)} ↗</button>`).join("")}</div></section><section class="lesson-section"><h3>What to watch for</h3><ul>${current.pitfalls.map((x) => `<li>${inlineReferences(x)}</li>`).join("")}</ul></section><section class="quiz-section"><p class="eyebrow">MAKE A PREDICTION</p><h2>Check your working model.</h2><p><small>Answer once, then see feedback immediately. “I don’t know” is useful evidence.</small></p>${current.questions.map(renderQuestion).join("")}</section>${s.review ? (current.findings_unlocked ? `<section class="lesson-section"><p class="eyebrow">YOUR VIEW FIRST, THEN THE AGENT’S</p><h2>Proposed review findings</h2>${current.findings.map((f) => renderFinding(f, current)).join("") || "<p>No supported findings were proposed for this module. This is not a safety certification.</p>"}</section>` : '<div class="findings-lock">Review findings unlock after you answer this module’s questions.</div>') : ""}`;
  } else if (current) {
    body = `<div class="preview-card"><p class="eyebrow">A MODULE IS ON ITS WAY</p><h2>${escape(current.title)}</h2><p>${escape(current.summary)}</p><p class="quiet">The agent is validating its code anchors and questions. This module will open as soon as it is ready.</p></div>`;
  } else {
    body =
      '<div class="preview-card"><h2>Finding the right starting point.</h2><p>The first module appears as soon as OpenCode writes and validates it. You do not have to wait for the whole round.</p></div>';
  }
  const retryable = ["error", "cancelled", "interrupted"].includes(s.status);
  const error = retryable
    ? `<div class="error">${escape(s.error || "This run stopped. Your validated modules and answers are saved.")} <button class="secondary" id="retry-round">Try another round →</button></div>`
    : "";
  const oldScroll = document.querySelector(".code-lines")?.scrollTop || 0;
  content.innerHTML = `${banner}${error}<div class="workspace-status">Round ${s.round} · ${Number(s.cost).toFixed(3)} USD reported · ${Math.round(s.seconds)}s total agent time</div><div class="workspace" style="--pane-width:${Number(localStorage.getItem("scire-pane-width")) || 390}px"><div class="lesson-body">${activity}${body}${s.complete ? '<div class="next-footer"><div><h3>Round complete.</h3><small>Choose what to understand next.</small></div><button class="primary" id="what-next">What next →</button></div>' : ""}${s.topics
    .filter((t) => t.answer)
    .map(
      (t) =>
        `<section class="topic-answer"><h3>${escape(t.question)}</h3>${markdown(t.answer)}</section>`,
    )
    .join(
      "",
    )}${askForm(s.id)}</div><div class="code-splitter" role="separator" aria-label="Resize code pane" aria-orientation="vertical" tabindex="0"></div><aside class="code-pane" id="code-pane"></aside></div>`;
  if (current?.status === "ready" && !anchor && !pinned)
    anchor = current.resolved[current.anchors[0].id];
  renderCode();
  const box = document.querySelector(".code-lines");
  if (box) box.scrollTop = oldScroll;
  content.querySelectorAll("[data-anchor]").forEach(
    (b) =>
      (b.onclick = () => {
        anchor = current.resolved[b.dataset.anchor];
        pinned = true;
        keyword = "";
        renderCode();
      }),
  );
  content.querySelectorAll("[data-answer]").forEach(
    (b) =>
      (b.onclick = async () => {
        b.disabled = true;
        try {
          await api(`sessions/${s.repo}/${s.id}/answer`, {
            key: b.dataset.answer,
            choice: b.dataset.choice,
          });
          await pollWorkspace(true);
        } catch (e) {
          toast(e.message);
          b.disabled = false;
        }
      }),
  );
  if (document.querySelector("#cancel-round"))
    document.querySelector("#cancel-round").onclick = async () => {
      await api(`sessions/${s.repo}/${s.id}/cancel`, {});
      await pollWorkspace(true);
    };
  if (document.querySelector("#what-next"))
    document.querySelector("#what-next").onclick = nextDialog;
  content.querySelectorAll("[data-draft]").forEach((t) => {
    t.onfocus = () => (editing = true);
    t.onblur = async () => {
      editing = false;
      await saveDraft(current.id, t.dataset.draft, t.value);
    };
    t.oninput = () => {
      autosize();
      clearTimeout(t.saveTimer);
      t.saveTimer = setTimeout(
        () => saveDraft(current.id, t.dataset.draft, t.value),
        500,
      );
    };
  });
  content.querySelectorAll("[data-stance]").forEach(
    (b) =>
      (b.onclick = async () => {
        const area = content.querySelector(`[data-draft="${b.dataset.fid}"]`);
        await saveDraft(
          current.id,
          b.dataset.fid,
          area.value,
          b.dataset.stance,
        );
        await pollWorkspace(true);
      }),
  );
  content.querySelectorAll("[data-preview]").forEach(
    (b) =>
      (b.onclick = async () => {
        const t = content.querySelector(`[data-draft="${b.dataset.preview}"]`);
        await saveDraft(current.id, b.dataset.preview, t.value);
        previewComment(current.id, b.dataset.preview);
      }),
  );
  if (document.querySelector("#retry-round"))
    document.querySelector("#retry-round").onclick = async () => {
      try {
        await api(`sessions/${s.repo}/${s.id}/start`, {});
        activeModule = null;
        await pollWorkspace(true);
      } catch (e) {
        toast(e.message);
      }
    };
  bindResize();
  bindAsk(s.id);
  autosize();
}
function renderCode() {
  const pane = document.querySelector("#code-pane");
  if (!pane) return;
  if (!anchor) {
    pane.innerHTML =
      '<div class="code-empty"><p class="eyebrow">KEEP THE SOURCE CLOSE</p><h3>The code behind the explanation.</h3><p>Choose a source reference to open a highlighted excerpt here. Click to pin it as you read.</p></div>';
    return;
  }
  const uses = [];
  if (keyword)
    for (const line of anchor.lines) {
      let from = 0;
      while ((from = line.text.indexOf(keyword, from)) !== -1) {
        uses.push(line.number);
        from += Math.max(1, keyword.length);
      }
    }
  const selected = uses.length ? uses[keywordIndex % uses.length] : null;
  function mark(line) {
    if (!keyword || line.number !== selected) return escape(line.text);
    return line.text
      .split(keyword)
      .map(escape)
      .join(`<mark>${escape(keyword)}</mark>`);
  }
  pane.innerHTML = `<div class="code-header"><div>${escape(anchor.path)}<small>LINES ${anchor.start_line}–${anchor.end_line} · ${anchor.key_lines.length} key line${anchor.key_lines.length === 1 ? "" : "s"}</small></div><button class="pin-button ${pinned ? "pinned" : ""}" id="pin-code">${pinned ? "Pinned · unpin" : "Pin code"}</button></div><div class="code-lines">${anchor.lines.map((line) => `<div class="code-line ${line.highlight ? "highlight" : ""} ${line.key ? "key-line" : ""}" data-line="${line.number}"><span class="line-no">${line.number}</span><code>${mark(line)}</code></div>`).join("")}</div><div class="look-chips">${anchor.look_for.map((word) => `<button class="${keyword === word ? "active" : ""}" data-keyword="${escape(word)}">Look for ${escape(word)}${keyword === word ? ` · ${uses.length ? (keywordIndex % uses.length) + 1 : 0}/${uses.length}` : ""}</button>`).join("")}</div>`;
  document.querySelector("#pin-code").onclick = () => {
    pinned = !pinned;
    renderCode();
  };
  pane.querySelectorAll("[data-keyword]").forEach(
    (b) =>
      (b.onclick = () => {
        keywordIndex = keyword === b.dataset.keyword ? keywordIndex + 1 : 0;
        keyword = b.dataset.keyword;
        renderCode();
      }),
  );
  if (selected)
    pane
      .querySelector(`[data-line="${selected}"]`)
      ?.scrollIntoView({ block: "nearest" });
}
function bindResize() {
  const handle = document.querySelector(".code-splitter"),
    grid = document.querySelector(".workspace");
  if (!handle) return;
  const set = (width) => {
    const w = Math.max(260, Math.min(720, width));
    grid.style.setProperty("--pane-width", w + "px");
    localStorage.setItem("scire-pane-width", String(w));
  };
  handle.onpointerdown = (e) => {
    handle.setPointerCapture(e.pointerId);
    handle.onpointermove = (e) =>
      set(grid.getBoundingClientRect().right - e.clientX);
    handle.onpointerup = () => (handle.onpointermove = null);
  };
  handle.onkeydown = (e) => {
    if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
      e.preventDefault();
      set(
        (Number(localStorage.getItem("scire-pane-width")) || 390) +
          (e.key === "ArrowLeft" ? 20 : -20),
      );
    }
  };
}
async function saveDraft(mid, fid, body, stance) {
  try {
    const existing = workspace.drafts?.[fid];
    const result = await api(
      `sessions/${workspace.repo}/${workspace.id}/finding/${mid}/${fid}`,
      { body, stance: stance || existing?.stance || "unsure" },
    );
    workspace.drafts ??= {};
    workspace.drafts[fid] = result;
  } catch (e) {
    toast(e.message);
  }
}
async function previewComment(mid, fid) {
  try {
    const s = workspace;
    const value = await api(
      `sessions/${s.repo}/${s.id}/finding/${mid}/${fid}/preview`,
    );
    modal.innerHTML = `<p class="eyebrow">NOT POSTED YET</p><h2>Review the exact comment.</h2><div class="comment-code">${escape(value.path)} · line ${value.line}<br>Head ${escape(value.head.slice(0, 12))}</div><div class="comment-body">${escape(value.body)}</div><p><small>This posts a single comment to GitHub. It does not approve or merge the pull request.</small></p><div class="dialog-actions"><button class="secondary" data-close>Keep editing</button><button class="primary" id="post-comment" ${s.review.kind !== "pr" || value.postable === false ? "disabled" : ""}>Post exact comment to GitHub</button></div>${value.postable === false ? '<p class="quiet">This anchor is outside added diff lines, so GitHub inline posting is unavailable. You can copy and use the draft manually.</p>' : ""}`;
    modal.showModal();
    modal.querySelector("[data-close]").onclick = () => modal.close();
    document.querySelector("#post-comment").onclick = async () => {
      const b = document.querySelector("#post-comment");
      b.disabled = true;
      try {
        const result = await api(
          `sessions/${s.repo}/${s.id}/finding/${mid}/${fid}/post`,
          { confirmation: value.confirmation, explicit_action: true },
        );
        modal.close();
        toast("Comment posted to GitHub");
        await pollWorkspace(true);
      } catch (e) {
        toast(e.message);
        b.disabled = false;
      }
    };
  } catch (e) {
    toast(e.message);
  }
}
async function nextDialog() {
  try {
    const s = workspace,
      value = await api(`sessions/${s.repo}/${s.id}/next`);
    modal.innerHTML = `<p class="eyebrow">FOLLOW THE EVIDENCE</p><h2>What would you like to understand next?</h2><p>Weakest areas first. These estimates include forgetting and changes in the code.</p><div class="next-options">${value.areas.map((a) => `<button data-next-area="${a.id}"><div>${escape(a.name)}<small>Focus a round on this area</small></div><span>${percent(a.mastery)}% →</span></button>`).join("")}${value.concepts
      .slice(0, 3)
      .map(
        (c) =>
          `<button data-next-concept="${c.id}"><div>${escape(c.name)}<small>One focused concept lesson</small></div><span>${percent(c.mastery)}% →</span></button>`,
      )
      .join(
        "",
      )}<button id="same-round"><div>Continue this learning path<small>Another round in this session</small></div><span>→</span></button></div><div class="dialog-actions"><button class="secondary" data-close>Finish for now</button></div>`;
    modal.showModal();
    const start = async (body) => {
      try {
        await api(`sessions/${s.repo}/${s.id}/start`, body);
        modal.close();
        activeModule = null;
        if (!pinned) anchor = null;
        await pollWorkspace(true);
      } catch (e) {
        toast(e.message);
      }
    };
    modal.querySelector("[data-close]").onclick = () => modal.close();
    modal.querySelectorAll("[data-next-area]").forEach(
      (b) =>
        (b.onclick = () =>
          start({
            depths: Object.fromEntries(
              s.map.areas.map((a) => [
                a.id,
                a.id === b.dataset.nextArea ? "standard" : "skip",
              ]),
            ),
          })),
    );
    modal
      .querySelectorAll("[data-next-concept]")
      .forEach(
        (b) => (b.onclick = () => start({ focus: b.dataset.nextConcept })),
      );
    document.querySelector("#same-round").onclick = () => start({});
  } catch (e) {
    toast(e.message);
  }
}
async function pollWorkspace(force = false) {
  if (!path || polling) return;
  polling = true;
  try {
    const value = await api(`sessions/${path[1]}/${path[2]}`);
    const signature = JSON.stringify(value);
    workspace = value;
    if (force || signature !== lastSignature) {
      if (!editing) {
        lastSignature = signature;
        renderWorkspace();
      }
    }
    if (workspace.review && Date.now() - headChecked > 30000) {
      headChecked = Date.now();
      api(`sessions/${path[1]}/${path[2]}/head`).catch(() => {});
    }
  } catch (e) {
    toast(e.message);
  } finally {
    polling = false;
  }
}
async function refresh() {
  try {
    state = await api("home");
    if (view === "session") await pollWorkspace(true);
    render();
  } catch (e) {
    content.innerHTML = `<div class="error">${escape(e.message)}. Start Scire from your terminal and use its browser link.</div>`;
  }
}
document.querySelectorAll("[data-view]").forEach(
  (b) =>
    (b.onclick = () => {
      if (path) {
        location.href = "/?view=" + b.dataset.view;
        return;
      }
      view = b.dataset.view;
      document
        .querySelectorAll("[data-view]")
        .forEach((x) => x.classList.toggle("selected", x === b));
      render();
    }),
);
const queryView = new URLSearchParams(location.search).get("view");
if (queryView) view = queryView;
document.querySelector("#profile-badge").onclick = () => {
  if (path) location.href = "/?view=settings";
  else {
    view = "settings";
    render();
  }
};
document.querySelector("#nav-toggle").onclick = () => {
  const collapsed = document
    .querySelector(".layout")
    .classList.toggle("nav-collapsed");
  document
    .querySelector("#nav-toggle")
    .setAttribute("aria-expanded", String(!collapsed));
};
document.querySelector("#repo-menu").onclick = () => {
  modal.innerHTML = `<h2>Choose a repository</h2><div class="row"><button data-repo="">All repositories</button></div>${(state?.repos || []).map((r) => `<div class="row"><button data-repo="${r.id}">${escape(r.name)}</button></div>`).join("")}<div class="dialog-actions"><button class="secondary" data-close>Close</button></div>`;
  modal.showModal();
  modal.querySelectorAll("[data-repo]").forEach(
    (b) =>
      (b.onclick = () => {
        selectedRepo = b.dataset.repo || null;
        modal.close();
        if (path) location.href = "/";
        else render();
      }),
  );
  modal.querySelector("[data-close]").onclick = () => modal.close();
};
refresh();
setInterval(() => {
  if (view === "session") pollWorkspace();
  else if (
    state?.repos.some((r) =>
      ["working", "missing", "queued"].includes(r.map.status),
    ) &&
    !editing
  )
    refresh();
}, 1600);
