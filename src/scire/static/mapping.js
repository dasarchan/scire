const duration = (seconds) => {
  const value = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
};
let current = null;
export function mappingView(container, repo, repos, actions) {
  const map = repo.map,
    busy = ["queued", "working", "missing"].includes(map.status);
  const key = repo.id + ":" + (map.started_at || "waiting");
  if (current?.key !== key || !container.querySelector(".mapping-view")) {
    container.innerHTML = `<section class="mapping-view"><div class="mapping-toolbar"><button class="secondary" id="mapping-back">← Workspace</button><select id="mapping-repos" aria-label="Mapping repository"></select></div><div class="mapping-heading"><div><div class="mapping-state"><i class="pulse"></i><span id="mapping-state"></span></div><h2 id="mapping-title"></h2><p id="mapping-description"></p></div><div class="mapping-time"><b id="mapping-elapsed"></b><span>elapsed</span></div></div><div class="mapping-feed-header"><span>Agent activity</span><span id="mapping-recent" role="status"></span></div><div class="mapping-feed" tabindex="0" aria-label="Live agent activity" aria-live="off"><div id="mapping-entries"></div><div class="mapping-wait">Waiting for the agent’s next update<span class="mapping-dots">…</span></div></div><div class="mapping-footer"><span id="mapping-summary"></span><div><button class="secondary" id="mapping-follow" hidden>Jump to latest ↓</button><button class="primary" id="mapping-action" hidden></button></div></div><div class="error" id="mapping-error" hidden></div></section>`;
    current = { key, nodes: new Map(), follow: true, signature: "" };
    const feed = container.querySelector(".mapping-feed");
    feed.onscroll = () => {
      current.follow =
        feed.scrollHeight - feed.scrollTop - feed.clientHeight < 70;
      container.querySelector("#mapping-follow").hidden = current.follow;
    };
    container.querySelector("#mapping-follow").onclick = () => {
      current.follow = true;
      feed.scrollTop = feed.scrollHeight;
    };
  }
  const get = (s) => container.querySelector(s);
  get("#mapping-back").onclick = actions.back;
  const select = get("#mapping-repos");
  const signature = repos.map((r) => r.id + r.map.status).join();
  if (select.dataset.signature !== signature) {
    select.replaceChildren(
      ...repos.map((r) => {
        const option = document.createElement("option");
        option.value = r.id;
        option.textContent =
          r.name +
          (["working", "queued"].includes(r.map.status)
            ? " · " + r.map.status
            : "");
        return option;
      }),
    );
    select.dataset.signature = signature;
  }
  select.value = repo.id;
  select.onchange = () => actions.select(select.value);
  get("#mapping-state").textContent =
    map.status === "ready"
      ? "Complete"
      : busy
        ? "Mapping in progress"
        : "Mapping stopped";
  get(".mapping-state .pulse").hidden = !busy;
  get("#mapping-title").textContent =
    map.status === "ready" ? `${repo.name} is ready` : `Mapping ${repo.name}`;
  get("#mapping-description").textContent =
    map.status === "ready"
      ? `${map.areas.length} areas · ${map.concepts.length} concepts. Choose what you’d like to learn.`
      : map.status === "queued"
        ? "Waiting for an available agent. Mapping starts automatically."
        : busy
          ? "The agent is tracing how this codebase fits together. You can leave this screen while it works."
          : "Your existing lessons and learning history are still available.";
  const end = map.finished_at || (busy ? Date.now() / 1000 : map.last_activity);
  get("#mapping-elapsed").textContent = map.started_at
    ? duration(end - map.started_at)
    : "—";
  const quiet = Math.max(
    0,
    Math.floor(Date.now() / 1000 - (map.last_activity || Date.now() / 1000)),
  );
  get("#mapping-recent").textContent = !busy
    ? map.status === "ready"
      ? "Finished"
      : "Stopped"
    : quiet < 10
      ? "Live"
      : `Still running · last output ${quiet}s ago`;
  get(".mapping-wait").hidden = !busy;
  const feed = get(".mapping-feed"),
    entries = get("#mapping-entries");
  const events = map.events || [];
  const ids = new Set(events.map((e) => e.id));
  for (const [id, node] of current.nodes)
    if (!ids.has(id)) {
      node.remove();
      current.nodes.delete(id);
    }
  for (const event of events) {
    let node = current.nodes.get(event.id);
    if (!node) {
      node = document.createElement("div");
      entries.append(node);
      current.nodes.set(event.id, node);
    }
    node.className =
      "mapping-entry mapping-" + (event.kind === "text" ? "text" : "tool");
    const text =
      (event.kind === "tool"
        ? event.status === "completed"
          ? "✓  "
          : event.status === "error"
            ? "!  "
            : "›  "
        : "") + event.text;
    if (node.textContent !== text) node.textContent = text;
  }
  if (!events.length) {
    get(".mapping-wait").textContent =
      map.activity || "Preparing the default-branch snapshot…";
  } else
    get(".mapping-wait").textContent = "Waiting for the agent’s next update…";
  if (current.follow) feed.scrollTop = feed.scrollHeight;
  get("#mapping-summary").textContent = map.metrics
    ? `${duration(map.metrics.seconds)} total · ${map.metrics.cost ? "$" + Number(map.metrics.cost).toFixed(3) + " reported" : "No cost reported by provider"}`
    : "Progress comes directly from OpenCode";
  const action = get("#mapping-action");
  action.hidden = busy;
  action.textContent =
    map.status === "ready" ? "Start learning →" : "Retry mapping →";
  action.onclick = map.status === "ready" ? actions.learn : actions.retry;
  get("#mapping-error").hidden = !map.error;
  get("#mapping-error").textContent = map.error || "";
}
