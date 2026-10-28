import { repoHome } from "./repo-home.js";
import { changesView } from "./changes.js";
import { mappingView } from "./mapping.js";
import { startOnboarding } from "./onboarding.js";
const token =
  location.hash.slice(1) || sessionStorage.getItem("scire-token") || "";
if (token) {
  sessionStorage.setItem("scire-token", token);
  history.replaceState(null, "", location.pathname + location.search);
}
const main = document.querySelector("#main"),
  content = document.querySelector("#content"),
  modal = document.querySelector("#modal");
let renderingModule = null,
  sessionTab = "lesson";
const renderedMarkdown = new Map();
let state,
  selectedRepo = new URLSearchParams(location.search).get("repo") || null,
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
const repoPath = location.pathname.match(/^\/r\/([a-z0-9]+)\/$/);
if (repoPath) selectedRepo = repoPath[1];
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
let mappingRepo = null;
const dismissedMaps = new Set();
const mappingKey = (r) =>
  r.id + ":" + (r.map.started_at || r.map.attempt_sha || "initial");
const showMapping = (rid) => {
  mappingRepo = rid;
  view = "mapping";
  render();
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
function setHeading(title, subtitle = "") {
  main.querySelector(":scope > h1").textContent = title;
  const description = main.querySelector(":scope > .subtitle");
  description.textContent = subtitle;
  description.hidden = !subtitle;
}
function currentAnchors() {
  return (
    (renderingModule || workspace?.modules.find((m) => m.id === activeModule))
      ?.resolved || {}
  );
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
  return escape(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(#scire:([a-z0-9_-]+)\)/g, (match, label, id) =>
      refs[id]
        ? `<button class="inline-reference" data-anchor="${escape(id)}">${label}</button>`
        : match,
    )
    .replace(/\[([a-z0-9_, -]+)\](?!\()/g, (match, group) => {
      const ids = group.split(",").map((x) => x.trim());
      return ids.every((id) => refs[id])
        ? ids
            .map(
              (id) =>
                `<button class="inline-reference" data-anchor="${escape(id)}">${escape(refs[id].path.split("/").at(-1))}:${refs[id].start_line}</button>`,
            )
            .join(" ")
        : match;
    });
}

function markdown(text) {
  text = referenceText(text);
  if (renderedMarkdown.has(text))
    return `<div class="prose">${renderedMarkdown.get(text)}</div>`;
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
      renderedMarkdown.set(text, html);
      if (node.isConnected) {
        node.innerHTML = html;
      }
    } catch {
      if (node.isConnected) node.textContent = text;
    }
  });
  return `<div class="prose" id="${key}"></div>`;
}
function autosize() {
  document.querySelectorAll("label").forEach((label, i) => {
    const control = label.nextElementSibling;
    if (control?.matches("input,textarea,select")) {
      control.id ||= "scire-field-" + i;
      label.htmlFor = control.id;
    }
  });
  document.querySelectorAll("textarea").forEach((t) => {
    const grow = () => {
      t.style.height = "auto";
      t.style.height = Math.min(500, t.scrollHeight) + "px";
    };
    t.addEventListener("input", grow);
    grow();
  });
}
function repositoryConnections() {
  return `<section class="repo-connections" id="repo-connections">${repositoryConnectionsMarkup()}</section>`;
}
function repositoryConnectionsMarkup() {
  return `<div class="repo-setup-heading"><h3>Connected repositories</h3><button type="button" class="secondary" id="manage-repos">Choose in terminal ↗</button></div>${state.repos.length ? state.repos.map((r) => `<div class="repo-connection"><span class="repo-check">✓</span><div><b>${escape(r.name)}</b><small>${escape(r.path)}</small></div></div>`).join("") : "<p>Run <code>scire setup</code> in a terminal. Scire finds Git repositories on your computer and lets you choose from a searchable list.</p>"}<p class="repo-hint">${state.repos.length ? "Your selection is managed in terminal setup. Learning history is kept when you disconnect a repository." : "Connect at least one repository to continue."}</p>`;
}
function bindRepositoryConnections() {
  const button = document.querySelector("#manage-repos");
  if (button)
    button.onclick = () => {
      modal.innerHTML = `<h2>Choose repositories in your terminal.</h2><p>Scire searches your folders for Git repositories. Use the arrow keys to move, Space to select, and Enter to connect. You can type to filter the list.</p><div class="terminal-command"><code>scire setup</code><button class="secondary" id="copy-setup-command">Copy command</button></div><p><small>Already connected repositories start selected. Your learning history is kept if you change the selection.</small></p><div class="dialog-actions"><button class="primary" data-close>Done</button></div>`;
      modal.showModal();
      modal.querySelector("[data-close]").onclick = () => modal.close();
      modal.querySelector("#copy-setup-command").onclick = async () => {
        try {
          await navigator.clipboard.writeText("scire setup");
          toast("Setup command copied");
        } catch {
          toast("Run scire setup in a terminal.");
        }
      };
    };
  const submit = document.querySelector('#setup-form button[type="submit"]');
  if (submit) submit.disabled = !state.repos.length;
}
let repositoryPolling = false;
let onboarding;
async function refreshRepositoryConnections() {
  if (repositoryPolling) return;
  repositoryPolling = true;
  try {
    const next = await api("home");
    const signature = (repos) =>
      JSON.stringify(repos.map((r) => [r.id, r.path]));
    const changed = signature(next.repos) !== signature(state.repos);
    state.repos = next.repos;
    if (onboarding) {
      onboarding.update(next.repos, next.profile);
      return;
    }
    if (changed) {
      const box = document.querySelector("#repo-connections");
      if (box) {
        box.innerHTML = repositoryConnectionsMarkup();
        bindRepositoryConnections();
      }
    }
    const model = document.querySelector('#setup-form input[name="model"]');
    if (
      model &&
      !model.value &&
      next.profile.model &&
      !model.closest(".model-picker").dataset.edited
    )
      model.closest(".model-picker").setModel(next.profile.model);
  } finally {
    repositoryPolling = false;
  }
}
function profileFields() {
  return `<section class="settings-section"><div class="section-intro"><h2>About you</h2><p>Lessons adapt to your experience.</p></div><div class="section-fields"><label for="profile-name">Your name</label><input id="profile-name" name="name" required placeholder="Alex" value="${escape(state.profile.name)}"><label for="profile-role">What do you work on?</label><textarea id="profile-role" name="role" placeholder="Your role and experience with this codebase">${escape(state.profile.role)}</textarea></div></section>`;
}
function modelPicker(name, label, optional = false, selectedValue) {
  const value = selectedValue ?? state.profile[name] ?? "";
  return `<fieldset class="model-picker" data-name="${name}" data-optional="${optional}"><legend>${label}</legend><input type="hidden" name="${name}" value="${escape(value)}"><div class="model-selects"><div><label for="${name}-provider">Provider</label><select id="${name}-provider" ${optional ? "" : "required"} aria-label="${label} provider"><option value="">Loading providers…</option></select></div><div><label for="${name}-model">Model</label><select id="${name}-model" aria-label="${label}" ${optional ? "" : "required"}><option value="">Loading models…</option></select></div></div>${optional ? '<p class="field-help">Use a faster model for short questions. Leave unset to use your teaching model.</p>' : ""}<div class="model-status" role="status"></div><button type="button" class="text-button model-manual-toggle">Enter a custom model ID</button><div class="model-manual" hidden><label for="${name}-custom">${label} ID</label><input id="${name}-custom" placeholder="provider/model" value="${escape(value)}" disabled></div></fieldset>`;
}
function modelFields() {
  return `<section class="settings-section"><div class="section-intro"><h2>Models</h2><p>Choose from your OpenCode providers.</p></div><div class="section-fields">${modelPicker("model", "Teaching model")}${modelPicker("cheap_model", "Quick answers", true)}<div class="provider-help">To connect another provider, run <code>scire setup --connect</code> in your terminal.</div></div></section>`;
}
let modelCatalogPromise;
function bindModelPickers() {
  document.querySelectorAll(".model-picker").forEach((field) => {
    const value = field.querySelector('input[type="hidden"]');
    const provider = field.querySelector('select[id$="-provider"]');
    const model = field.querySelector('select[id$="-model"]');
    const custom = field.querySelector(".model-manual input");
    const toggle = field.querySelector(".model-manual-toggle");
    const status = field.querySelector(".model-status");
    const optional = field.dataset.optional === "true";
    let catalog = [],
      manual = false;
    const remember = () => {
      field.dataset.edited = "true";
    };
    const render = () => {
      const priorProvider =
        field.dataset.edited && !manual ? provider.value : "";
      const models = [
        ...new Set([...catalog, ...(value.value ? [value.value] : [])]),
      ].sort();
      const providers = [...new Set(models.map((id) => id.split("/")[0]))];
      provider.innerHTML =
        `<option value="">${optional ? "Use teaching model" : "Choose provider"}</option>` +
        providers
          .map((id) => `<option value="${escape(id)}">${escape(id)}</option>`)
          .join("");
      provider.value = priorProvider || value.value.split("/")[0] || "";
      renderModels(models);
    };
    const renderModels = (
      models = [
        ...new Set([...catalog, ...(value.value ? [value.value] : [])]),
      ].sort(),
    ) => {
      model.innerHTML =
        `<option value="">${provider.value ? "Choose model" : optional ? "Same as teaching model" : "Select a provider first"}</option>` +
        models
          .filter((id) => id.startsWith(provider.value + "/"))
          .map(
            (id) =>
              `<option value="${escape(id)}">${escape(id.slice(id.indexOf("/") + 1))}</option>`,
          )
          .join("");
      model.disabled = manual || !provider.value;
      model.value = value.value;
    };
    field.setModel = (id) => {
      value.value = id;
      custom.value = id;
      provider.value = "";
      render();
    };
    provider.onchange = () => {
      remember();
      value.value = "";
      renderModels();
    };
    model.onchange = () => {
      remember();
      value.value = model.value;
      custom.value = value.value;
    };
    custom.oninput = () => {
      remember();
      value.value = custom.value.trim();
      custom.setCustomValidity(
        (!value.value && optional) || /^[\w.-]+\/[^\s]+$/.test(value.value)
          ? ""
          : "Use provider/model, for example openai/gpt-5.",
      );
    };
    toggle.onclick = () => {
      manual = !manual;
      field.querySelector(".model-selects").hidden = manual;
      field.querySelector(".model-manual").hidden = !manual;
      custom.disabled = !manual;
      custom.required = manual && !optional;
      provider.disabled = manual;
      model.disabled = manual || !provider.value;
      toggle.textContent = manual
        ? "Choose from OpenCode models"
        : "Enter a custom model ID";
      if (manual) {
        custom.value = value.value;
        custom.focus();
        custom.oninput();
      } else {
        provider.value = "";
        render();
        provider.focus();
      }
    };
    const load = async () => {
      status.textContent = "Loading models from OpenCode…";
      try {
        modelCatalogPromise ||= api("models").catch((error) => {
          modelCatalogPromise = null;
          throw error;
        });
        const result = await modelCatalogPromise;
        if (!field.isConnected) return;
        catalog = result.models;
        render();
        status.textContent = catalog.length
          ? ""
          : "No models found. Connect a provider or enter a custom model ID.";
      } catch (error) {
        if (!field.isConnected) return;
        render();
        status.replaceChildren(
          document.createTextNode("Couldn’t load OpenCode models. "),
        );
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "text-button";
        retry.textContent = "Retry";
        retry.onclick = load;
        status.append(retry);
      }
    };
    render();
    load();
  });
}
function setup() {
  if (onboarding) return;
  onboarding = startOnboarding({
    container: content,
    profile: state.profile,
    getRepos: () => state.repos,
    modelPicker,
    bindModels: bindModelPickers,
    escape,
    complete: async (value) => {
      await api("setup", value);
      onboarding = null;
      view = "home";
      await refresh();
    },
  });
}
function areaTree(map, learnButton = true, parent = null) {
  return map.areas
    .filter((a) => (a.parent ?? null) === parent)
    .map(
      (a) =>
        `<details><summary><span>${escape(a.name)}</span><span class="bar"><span style="width:${a.assessed_count ? percent(a.mastery) + "%" : "—"}"></span></span><small>${percent(a.mastery)}%</small></summary><p>${escape(a.summary)}</p>${areaTree(map, learnButton, a.id)}${map.concepts
          .filter((c) => c.parent === a.id)
          .map(
            (c) =>
              `<div class="concept-leaf"><div><b>${escape(c.name)}</b><p>${c.attempts ? percent(c.mastery) + "% estimated · " + c.attempts + " answers" : "Not assessed yet"}${c.code_changed ? " · code changed" : ""}</p></div>${learnButton ? `<button class="secondary" data-focus="${escape(c.id)}">Learn this →</button>` : ""}</div>`,
          )
          .join("")}</details>`,
    )
    .join("");
}
async function openNew(rid, target = "learn", focus = null, options = {}) {
  try {
    const result = await api("sessions", {
      repo: rid,
      target,
      focus,
      ...options,
    });
    location.href = result.url;
  } catch (e) {
    toast(e.message);
  }
}
function conceptsDialog(rid) {
  const repo = state.repos.find((r) => r.id === rid);
  modal.innerHTML = `<h2>Concept mastery</h2><p class="quiet">Estimates come from your answers and adjust for time and code changes. Untested concepts remain uncertain.</p><div class="knowledge-tree">${areaTree(repo.map)}</div><div class="dialog-actions"><button class="secondary" id="concept-calibrate">Take calibration</button><button class="secondary" data-close>Close</button></div>`;
  modal.showModal();
  modal.querySelector("#concept-calibrate").onclick = () => {
    modal.close();
    openNew(rid, "learn", null, { calibration: true, minutes: 2 });
  };
  modal.querySelector("[data-close]").onclick = () => modal.close();
  modal.querySelectorAll("[data-focus]").forEach(
    (b) =>
      (b.onclick = () => {
        modal.close();
        openNew(rid, "learn", b.dataset.focus);
      }),
  );
}
function render() {
  if (!state) return;
  if (!selectedRepo || !state.repos.some((r) => r.id === selectedRepo)) {
    const saved = localStorage.getItem("scire-repo");
    selectedRepo =
      state.repos.find((r) => r.id === saved)?.id || state.repos[0]?.id || null;
  }
  if (selectedRepo) localStorage.setItem("scire-repo", selectedRepo);
  document.body.classList.toggle("onboarding-active", !state.profile.setup);
  document
    .querySelectorAll("[data-view]")
    .forEach((b) => b.classList.toggle("selected", b.dataset.view === view));
  document.querySelector("#profile-badge").textContent = (
    state.profile.name || "You"
  )
    .slice(0, 1)
    .toUpperCase();
  const repos = selectedRepo
    ? state.repos.filter((r) => r.id === selectedRepo)
    : state.repos;
  document.querySelector("#repo-label").textContent = selectedRepo
    ? repos[0]?.name || "All repositories"
    : "All repositories";
  if (!state.profile.setup) {
    setup();
    return;
  }
  if (view === "home") {
    const active = repos.find(
      (r) =>
        ["working", "queued"].includes(r.map.status) &&
        !dismissedMaps.has(mappingKey(r)),
    );
    if (active) {
      mappingRepo = active.id;
      view = "mapping";
    }
  }
  document.body.classList.toggle("mapping-active", view === "mapping");
  if (view === "mapping") {
    const repo = state.repos.find((r) => r.id === mappingRepo);
    if (!repo) {
      view = "home";
      render();
      return;
    }
    setHeading("");
    mappingView(content, repo, state.repos, {
      back: () => {
        dismissedMaps.add(mappingKey(repo));
        view = "home";
        render();
      },
      select: showMapping,
      learn: () => openNew(repo.id),
      retry: async () => {
        try {
          await api(`maps/${repo.id}/build`, {});
          await refresh();
        } catch (e) {
          toast(e.message);
        }
      },
    });
    return;
  }
  if (view === "session") {
    renderWorkspace();
    return;
  }
  document.querySelector("#session-nav").innerHTML = "";
  if (view === "knowledge") {
    setHeading("Knowledge");
    content.innerHTML = repos
      .map(
        (r) =>
          `<section class="card"><div class="card-heading"><h2>${escape(r.name)}</h2><span>${r.map.concepts.length} concepts</span></div><div class="knowledge-tree">${areaTree(r.map)}</div>${!r.map.areas.length ? "<p>The map is still being prepared.</p>" : ""}</section>`,
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
    setHeading("Settings");
    content.innerHTML = `<section class="setup"><form id="settings-form">${profileFields()}${modelFields()}<div class="form-actions"><button class="primary">Save settings</button></div></form>${repositoryConnections()}<div class="card-footer"><button class="secondary" id="quit-server">Quit Scire</button></div></section>`;
    bindModelPickers();
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
    bindRepositoryConnections();
    document.querySelector("#quit-server").onclick = async () => {
      await api("quit", {});
      toast("Scire is stopping. You can close this tab.");
    };
    autosize();
    return;
  }
  const repo = state.repos.find((r) => r.id === selectedRepo);
  setHeading(repo?.name || "Repositories");
  if (repo && !path && view === "home")
    history.replaceState(null, "", "/r/" + repo.id + "/");
  repoHome(content, {
    repo,
    sessions: state.sessions,
    escape,
    percent,
    ago,
    api,
    actions: {
      concepts: () => conceptsDialog(repo.id),
      learn: () => openNew(repo.id),
      calibrate: () =>
        openNew(repo.id, "learn", null, { calibration: true, minutes: 2 }),
      skipCalibration: async () => {
        await api(`repos/${repo.id}/onboarding`, { calibration: "skipped" });
        await refresh();
      },
      review: (target) => openNew(repo.id, target),
      activity: () => showMapping(repo.id),
      build: async () => {
        try {
          await api(`maps/${repo.id}/build`, {});
          mappingRepo = repo.id;
          view = "mapping";
          await refresh();
        } catch (e) {
          toast(e.message);
        }
      },
    },
  });
}

function renderDepth() {
  const s = workspace;
  content.innerHTML = `${s.review ? sessionTabs(s) : ""}<section class="card depth-form"><h2>${s.review ? "Set your review budget" : "Make this lesson yours"}</h2><p>Choose how much time to spend. Scire includes reading, code and questions in that budget.</p><form id="depth-form"><div class="lesson-preferences"><label>Reading budget<select name="minutes" aria-label="Reading budget">${[2, 5, 10].map((n) => `<option value="${n}" ${n === (s.reading_minutes || 5) ? "selected" : ""}>${n} minutes</option>`).join("")}</select></label>${!s.review ? `<label class="calibration-option"><input type="checkbox" name="calibration" ${s.calibration ? "checked" : ""}><span><b>Start with a calibration quiz</b><small>Sample what you know before choosing a focus. Optional.</small></span></label>` : ""}</div><details class="area-depths"><summary>Adjust depth by area</summary><div class="depth-list">${s.map.areas.map((a) => `<div class="row"><div><h3>${escape(a.name)}</h3><p>${escape(a.summary)}</p></div><select name="area:${escape(a.id)}" aria-label="Depth for ${escape(a.name)}">${["skip", "skim", "standard", "deep"].map((d) => `<option value="${d}" ${(s.depths[a.id] || "standard") === d ? "selected" : ""}>${d[0].toUpperCase() + d.slice(1)}</option>`).join("")}</select></div>`).join("")}</div></details><div class="card-footer"><span>One continuous lesson. Your answers are saved as you go.</span><button class="primary">${s.review ? "Prepare review" : "Start learning"} →</button></div></form></section>`;
  bindSessionTabs();
  document.querySelector("#depth-form").onsubmit = async (e) => {
    e.preventDefault();
    const form = e.target;
    const depths = Object.fromEntries(
      s.map.areas.map((a) => [a.id, form.elements["area:" + a.id].value]),
    );
    try {
      await api(`sessions/${s.repo}/${s.id}/start`, {
        depths,
        minutes: Number(form.elements.minutes.value),
        calibration: !!form.elements.calibration?.checked,
        focus: s.pending_focus || s.focus,
      });
      await pollWorkspace(true);
    } catch (e) {
      toast(e.message);
    }
  };
}
function sessionTabs(s) {
  return s.review
    ? `<div class="session-tabs" role="tablist" aria-label="Review view"><button role="tab" data-session-tab="lesson" aria-selected="${sessionTab === "lesson"}">Lesson</button><button role="tab" data-session-tab="changes" aria-selected="${sessionTab === "changes"}">Changes <span>${s.review.files?.length || ""}</span></button></div>`
    : "";
}
function bindSessionTabs() {
  content.querySelectorAll("[data-session-tab]").forEach(
    (b) =>
      (b.onclick = () => {
        sessionTab = b.dataset.sessionTab;
        renderWorkspace();
      }),
  );
}

function renderDiagram(value) {
  if (!value?.nodes?.length) return "";
  const nodes = value.nodes,
    w = 540,
    h = nodes.length * 85 + 25;
  const positions = Object.fromEntries(
    nodes.map((n, i) => [n.id, { x: 270, y: 45 + i * 85 }]),
  );
  return `<div class="diagram-box"><svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Flow diagram"><defs><marker id="arrow-${escape(renderingModule?.id || activeModule)}" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#697c96"/></marker></defs>${value.edges
    .map((e) => {
      const a = positions[e.from],
        b = positions[e.to];
      return `<path d="M${a.x},${a.y + 20} L${b.x},${b.y - 22}" fill="none" stroke="#697c96" marker-end="url(#arrow-${escape(renderingModule?.id || activeModule)})"/>${e.label ? `<text x="${a.x + 15}" y="${(a.y + b.y) / 2}" fill="#919aa9" font-size="10">${escape(e.label)}</text>` : ""}`;
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
  return `<section class="finding" data-finding="${escape(f.key)}"><div class="card-heading"><h3>${escape(f.title)}</h3><span class="pill">${escape(f.severity)}</span></div><div class="finding-label">Failure scenario</div><p>${escape(f.scenario)}</p><div class="finding-label">Evidence and impact</div><p>${escape(f.evidence)}</p><p>${escape(f.impact)}</p><button class="secondary" data-anchor="${escape(f.ref)}">Inspect evidence ↗</button><div class="stance">${["agree", "unsure", "disagree"].map((x) => `<button class="${draft.stance === x ? "active" : ""}" data-stance="${x}" data-fid="${escape(f.key)}">${x[0].toUpperCase() + x.slice(1)}</button>`).join("")}</div><label>Comment draft — editable, not posted</label><textarea data-draft="${escape(f.key)}">${escape(draft.body)}</textarea><div class="card-footer"><small>${workspace.posted?.[f.key] ? "Posted to GitHub" : "Nothing leaves Scire until you explicitly post."}</small><button class="secondary" data-preview="${escape(f.key)}">Preview exact comment →</button></div></section>`;
}
function lessonSection(m) {
  renderingModule = m;
  let html;
  if (m.status !== "ready")
    html = `<article class="continuous-module preview-card" id="lesson-${escape(m.id)}" data-lesson-module="${escape(m.id)}"><h2>${escape(m.title)}</h2><p>${escape(m.summary)}</p><small>Preparing code references and questions…</small></article>`;
  else {
    const questions = (after) =>
      m.questions
        .map((q, i) =>
          (q.after || ["flow", "key_code", "pitfalls"][i % 3]) === after
            ? renderQuestion(q, i)
            : "",
        )
        .join("");
    html = `<article class="continuous-module" id="lesson-${escape(m.id)}" data-lesson-module="${escape(m.id)}"><div class="module-title"><h2>${escape(m.title)}</h2><span class="pill">ROUND ${m.round}</span></div><div class="module-summary">${markdown(m.summary)}</div><section class="lesson-section"><h3>Why it exists</h3>${markdown(m.why)}</section>${questions("why")}<section class="lesson-section"><h3>Follow the flow</h3><ol>${m.flow.map((x) => `<li>${inlineReferences(x)}</li>`).join("")}</ol></section>${renderDiagram(m.diagram)}${questions("flow")}<section class="lesson-section"><h3>The key code</h3>${markdown(m.key_code)}<div class="anchor-links">${m.anchors.map((a) => `<button data-anchor="${escape(a.id)}">${escape(a.path)} ↗</button>`).join("")}</div></section>${questions("key_code")}<section class="lesson-section"><h3>What to watch for</h3><ul>${m.pitfalls.map((x) => `<li>${inlineReferences(x)}</li>`).join("")}</ul></section>${questions("pitfalls")}${workspace.review ? (m.findings_unlocked ? `<section class="lesson-section"><h3>Proposed review findings</h3>${m.findings.map((f) => renderFinding(f, m)).join("") || '<p class="quiet">No supported findings were proposed for this section.</p>'}</section>` : '<div class="findings-lock">Findings unlock after you answer this section’s questions.</div>') : ""}</article>`;
  }
  renderingModule = null;
  return html;
}
function moduleFor(node) {
  const id = node.closest("[data-lesson-module]")?.dataset.lessonModule;
  return workspace.modules.find((m) => m.id === (id || activeModule));
}
function showAnchor(node, id) {
  const owner = moduleFor(node);
  if (!owner?.resolved?.[id]) return;
  activeModule = owner.id;
  anchor = owner.resolved[id];
  pinned = true;
  keyword = "";
  renderCode();
}
content.addEventListener("click", (e) => {
  const link = e.target.closest('a[href^="#scire:"]');
  if (link) {
    e.preventDefault();
    showAnchor(link, link.getAttribute("href").slice(7));
  }
});
function renderWorkspace() {
  if (!workspace) {
    content.innerHTML = "<p>Opening your session…</p>";
    return;
  }
  const s = workspace;
  setHeading(
    s.title,
    s.review ? `Pinned at ${s.review.head.slice(0, 10)}` : "",
  );
  if (s.review && sessionTab === "changes") {
    content.innerHTML = sessionTabs(s) + '<div id="changes-content"></div>';
    bindSessionTabs();
    changesView(content.querySelector("#changes-content"), s, api, escape);
    return;
  }
  if (!s.started_learning) {
    renderDepth();
    return;
  }
  const modules = [...s.modules].sort(
    (a, b) => a.round - b.round || a.index - b.index,
  );
  if (!activeModule || !modules.some((m) => m.id === activeModule))
    activeModule =
      modules.find((m) => m.status === "ready")?.id || modules[0]?.id;
  document.querySelector("#session-nav").innerHTML =
    `<div class="nav-label">On this page</div>${modules.map((m) => `<button class="${m.id === activeModule ? "active" : ""}" data-module="${escape(m.id)}"><small>${m.status === "ready" && m.questions.every((q) => s.answers[q.key]) ? "✓" : String((m.index || 0) + 1).padStart(2, "0")}</small>${escape(m.title)}</button>`).join("")}`;
  document.querySelectorAll("[data-module]").forEach(
    (b) =>
      (b.onclick = () => {
        activeModule = b.dataset.module;
        document.querySelector("#lesson-" + activeModule)?.scrollIntoView({
          behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "instant"
            : "smooth",
          block: "start",
        });
        document
          .querySelectorAll("[data-module]")
          .forEach((n) => n.classList.toggle("active", n === b));
        const m = modules.find((m) => m.id === activeModule);
        if (!pinned && m?.resolved) {
          anchor = m.resolved[m.anchors[0].id];
          renderCode();
        }
      }),
  );
  const busy = ["working", "queued"].includes(s.status);
  const activity = busy
    ? `<div class="activity-card"><p><i class="pulse"></i>${s.status === "queued" ? "Queued" : "Preparing your lesson"} · ${Math.max(0, Math.floor(Date.now() / 1000 - (s.round_started_at || Date.now() / 1000)))}s</p>${s.activity
        .slice(-2)
        .map((a) => `<p>${escape(a.text)}</p>`)
        .join(
          "",
        )}<button class="secondary" id="cancel-round">Stop this run</button></div>`
    : "";
  const error = ["error", "cancelled", "interrupted"].includes(s.status)
    ? `<div class="error">${escape(s.error || "This run stopped. Your lessons and answers are saved.")} <button class="secondary" id="retry-round">Retry →</button></div>`
    : "";
  const oldScroll = document.querySelector(".code-lines")?.scrollTop || 0;
  content.innerHTML = `${sessionTabs(s)}${s.head_moved ? '<div class="head-banner">The PR head has changed. This review is pinned to an earlier revision.</div>' : ""}${error}<div class="workspace-status"><span>${s.reading?.minutes || s.reading_minutes || 5} min read & questions · ${Object.keys(s.answers).length}/${modules.reduce((n, m) => n + (m.questions?.length || 0), 0)} answered</span><span>${Number(s.cost).toFixed(3)} USD reported · ${Math.round(s.seconds)}s agent time</span></div><div class="workspace continuous-workspace" style="--pane-width:${Number(localStorage.getItem("scire-pane-width")) || 390}px"><div class="lesson-body">${modules.length ? modules.map(lessonSection).join("") : '<div class="preview-card"><h2>Preparing the first section</h2><p>You can begin reading as soon as the first section arrives.</p></div>'}${activity}${s.complete ? '<div class="next-footer"><div><h3>Round complete.</h3><small>Choose what to understand next.</small></div><button class="primary" id="what-next">What next →</button></div>' : ""}</div><div class="code-splitter" role="separator" aria-label="Resize code pane" aria-orientation="vertical" tabindex="0"></div><aside class="code-pane" id="code-pane"></aside></div>`;
  const current = modules.find((m) => m.id === activeModule);
  if (!anchor && !pinned && current?.resolved)
    anchor = current.resolved[current.anchors[0].id];
  renderCode();
  if (document.querySelector(".code-lines"))
    document.querySelector(".code-lines").scrollTop = oldScroll;
  bindSessionTabs();
  content
    .querySelectorAll("[data-anchor]")
    .forEach((b) => (b.onclick = () => showAnchor(b, b.dataset.anchor)));
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
  const cancel = document.querySelector("#cancel-round");
  if (cancel)
    cancel.onclick = async () => {
      await api(`sessions/${s.repo}/${s.id}/cancel`, {});
      await pollWorkspace(true);
    };
  const next = document.querySelector("#what-next");
  if (next) next.onclick = nextDialog;
  content.querySelectorAll("[data-draft]").forEach((t) => {
    t.onfocus = () => (editing = true);
    t.onblur = async () => {
      editing = false;
      await saveDraft(moduleFor(t).id, t.dataset.draft, t.value);
    };
    t.oninput = () => {
      autosize();
      clearTimeout(t.saveTimer);
      t.saveTimer = setTimeout(
        () => saveDraft(moduleFor(t).id, t.dataset.draft, t.value),
        500,
      );
    };
  });
  content.querySelectorAll("[data-stance]").forEach(
    (b) =>
      (b.onclick = async () => {
        const m = moduleFor(b),
          area = b
            .closest("[data-lesson-module]")
            .querySelector(`[data-draft="${b.dataset.fid}"]`);
        await saveDraft(m.id, b.dataset.fid, area.value, b.dataset.stance);
        await pollWorkspace(true);
      }),
  );
  content.querySelectorAll("[data-preview]").forEach(
    (b) =>
      (b.onclick = async () => {
        const m = moduleFor(b),
          t = b
            .closest("[data-lesson-module]")
            .querySelector(`[data-draft="${b.dataset.preview}"]`);
        await saveDraft(m.id, b.dataset.preview, t.value);
        previewComment(m.id, b.dataset.preview);
      }),
  );
  const retry = document.querySelector("#retry-round");
  if (retry)
    retry.onclick = async () => {
      try {
        await api(`sessions/${s.repo}/${s.id}/start`, {});
        await pollWorkspace(true);
      } catch (e) {
        toast(e.message);
      }
    };
  bindResize();
  autosize();
}

function renderCode() {
  const pane = document.querySelector("#code-pane");
  if (!pane) return;
  if (!anchor) {
    pane.innerHTML =
      '<div class="code-empty"><h3>Source</h3><p>Choose a source reference to open a highlighted excerpt here. Click to pin it as you read.</p></div>';
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
  pane.innerHTML = `<div class="code-header"><div>${escape(anchor.path)}<small>Lines ${anchor.start_line}–${anchor.end_line} · ${anchor.key_lines.length} key line${anchor.key_lines.length === 1 ? "" : "s"}</small></div><button class="pin-button ${pinned ? "pinned" : ""}" id="pin-code">${pinned ? "Pinned · unpin" : "Pin code"}</button></div><div class="code-lines">${anchor.lines.map((line) => `<div class="code-line ${line.highlight ? "highlight" : ""} ${line.key ? "key-line" : ""}" data-line="${line.number}"><span class="line-no">${line.number}</span><code>${mark(line)}</code></div>`).join("")}</div><div class="look-chips">${anchor.look_for.map((word) => `<button class="${keyword === word ? "active" : ""}" data-keyword="${escape(word)}">Look for ${escape(word)}${keyword === word ? ` · ${uses.length ? (keywordIndex % uses.length) + 1 : 0}/${uses.length}` : ""}</button>`).join("")}</div>`;
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
    modal.innerHTML = `<h2>Review the exact comment.</h2><div class="comment-code">${escape(value.path)} · line ${value.line}<br>Head ${escape(value.head.slice(0, 12))}</div><div class="comment-body">${escape(value.body)}</div><p><small>This posts a single comment to GitHub. It does not approve or merge the pull request.</small></p><div class="dialog-actions"><button class="secondary" data-close>Keep editing</button><button class="primary" id="post-comment" ${s.review.kind !== "pr" || value.postable === false ? "disabled" : ""}>Post exact comment to GitHub</button></div>${value.postable === false ? '<p class="quiet">This anchor is outside added diff lines, so GitHub inline posting is unavailable. You can copy and use the draft manually.</p>' : ""}`;
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
    modal.innerHTML = `<h2>What would you like to understand next?</h2><p>Weakest areas first. These estimates include forgetting and changes in the code.</p><div class="next-options">${value.areas.map((a) => `<button data-next-area="${a.id}"><div>${escape(a.name)}<small>Focus a round on this area</small></div><span>${percent(a.mastery)}% →</span></button>`).join("")}${value.concepts
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
    const signature = JSON.stringify({
      ...value,
      map: value.started_learning ? undefined : value.map,
    });
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
  } finally {
    document.body.removeAttribute("data-loading");
  }
}
document.querySelectorAll("[data-view]").forEach(
  (b) =>
    (b.onclick = () => {
      if (path) {
        location.href = "/r/" + selectedRepo + "/?view=" + b.dataset.view;
        return;
      }
      view = b.dataset.view;
      if (selectedRepo)
        history.replaceState(
          null,
          "",
          "/r/" + selectedRepo + "/" + (view === "home" ? "" : "?view=" + view),
        );
      document
        .querySelectorAll("[data-view]")
        .forEach((x) => x.classList.toggle("selected", x === b));
      render();
    }),
);
const queryView = new URLSearchParams(location.search).get("view");
if (queryView) view = queryView;
document.querySelector("#profile-badge").onclick = () => {
  if (path) location.href = "/r/" + selectedRepo + "/?view=settings";
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
const repoTrigger = document.querySelector("#repo-menu"),
  repoDropdown = document.querySelector("#repo-dropdown"),
  repoFilter = document.querySelector("#repo-filter"),
  repoOptions = document.querySelector("#repo-options");
function closeRepoDropdown(restoreFocus = false) {
  repoDropdown.hidden = true;
  repoTrigger.setAttribute("aria-expanded", "false");
  if (restoreFocus) repoTrigger.focus();
}
function positionRepoDropdown() {
  if (repoDropdown.hidden) return;
  const rect = repoTrigger.getBoundingClientRect();
  const left = Math.max(
    12,
    Math.min(rect.left, innerWidth - repoDropdown.offsetWidth - 12),
  );
  repoDropdown.style.left = left + "px";
  repoDropdown.style.top = rect.bottom + 8 + "px";
  repoDropdown.style.maxHeight =
    Math.min(440, innerHeight - rect.bottom - 20) + "px";
}
function renderRepoOptions() {
  const query = repoFilter.value.trim().toLowerCase();
  const repos = (state?.repos || []).filter((r) =>
    (r.name + " " + r.path).toLowerCase().includes(query),
  );
  const icon =
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M2.5 6V4.5h5l2 2h8v9h-15z"/></svg>';
  const option = (id, name, detail, fullPath = detail) =>
    `<button type="button" role="option" tabindex="-1" class="repo-option" aria-selected="${(selectedRepo || "") === id}" data-repo="${escape(id)}">${icon}<span class="repo-option-copy"><strong>${escape(name)}</strong><small title="${escape(fullPath)}">${escape(detail)}</small></span><svg class="repo-checkmark" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m3 8 3 3 7-7"/></svg></button>`;
  repoOptions.innerHTML =
    repos
      .map((r) =>
        option(
          r.id,
          r.name,
          r.path.split("/").filter(Boolean).slice(-2).join("/"),
          r.path,
        ),
      )
      .join("") +
    (query && !repos.length
      ? '<div class="repo-no-results" role="status">No repositories found.</div>'
      : "");
  repoOptions.querySelectorAll("[data-repo]").forEach((button) => {
    button.onclick = () => {
      selectedRepo = button.dataset.repo || null;
      localStorage.setItem("scire-repo", selectedRepo);
      view = "home";
      closeRepoDropdown(true);
      if (path) {
        location.href = selectedRepo
          ? "/r/" + encodeURIComponent(selectedRepo) + "/"
          : "/";
        return;
      }
      history.replaceState(null, "", "/r/" + selectedRepo + "/");
      render();
    };
  });
}
function openRepoDropdown() {
  repoFilter.value = "";
  renderRepoOptions();
  const count = state?.repos.length || 0;
  document.querySelector("#repo-count").textContent = count + " connected";
  repoDropdown.hidden = false;
  repoTrigger.setAttribute("aria-expanded", "true");
  positionRepoDropdown();
  repoFilter.focus();
}
repoTrigger.onclick = () =>
  repoDropdown.hidden ? openRepoDropdown() : closeRepoDropdown();
repoTrigger.onkeydown = (event) => {
  if (["ArrowDown", "ArrowUp"].includes(event.key)) {
    event.preventDefault();
    openRepoDropdown();
    const options = repoOptions.querySelectorAll("[role=option]");
    (event.key === "ArrowUp"
      ? options[options.length - 1]
      : options[0]
    )?.focus();
  }
};
repoFilter.oninput = renderRepoOptions;
repoDropdown.onkeydown = (event) => {
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  // Home and End still edit the search field normally.
  if (event.target === repoFilter && ["Home", "End"].includes(event.key))
    return;
  event.preventDefault();
  const options = [...repoOptions.querySelectorAll("[role=option]")];
  const index = options.indexOf(document.activeElement);
  const next =
    event.key === "Home"
      ? 0
      : event.key === "End"
        ? options.length - 1
        : event.key === "ArrowDown"
          ? (index + 1) % options.length
          : (index <= 0 ? options.length : index) - 1;
  options[next]?.focus();
};
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !repoDropdown.hidden) {
    event.preventDefault();
    closeRepoDropdown(true);
  }
});
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest(".repo-switcher")) closeRepoDropdown();
});
document
  .querySelector(".repo-switcher")
  .addEventListener("focusout", (event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) closeRepoDropdown();
  });
window.addEventListener("resize", positionRepoDropdown);
document.querySelector("#repo-settings").onclick = () => {
  closeRepoDropdown();
  if (path) location.href = "/r/" + selectedRepo + "/?view=settings";
  else {
    view = "settings";
    render();
    document.querySelector("#manage-repos")?.focus();
  }
};

refresh();
setInterval(() => {
  if (onboarding) refreshRepositoryConnections().catch(() => {});
  else if (view === "mapping") refresh();
  else if (view === "session") pollWorkspace();
  else if (document.querySelector("#repo-connections"))
    refreshRepositoryConnections().catch(() => {});
  else if (
    (state?.repos.some(
      (r) =>
        r.id === selectedRepo && ["working", "queued"].includes(r.map.status),
    ) ||
      state?.sessions.some(
        (s) =>
          s.repo === selectedRepo && ["working", "queued"].includes(s.status),
      )) &&
    !editing
  )
    refresh();
}, 1600);
