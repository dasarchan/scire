const draftKey = "scire-onboarding-v1";

export function startOnboarding({
  container,
  profile,
  getRepos,
  modelPicker,
  bindModels,
  escape,
  complete,
}) {
  let saved = {};
  try {
    saved = JSON.parse(sessionStorage.getItem(draftKey) || "{}");
  } catch {}
  const draft = {};
  for (const key of ["name", "role", "model", "cheap_model"])
    draft[key] =
      typeof saved?.[key] === "string" ? saved[key] : profile[key] || "";
  draft.map_now = saved?.map_now !== false;
  let step = Number.isInteger(saved?.step)
    ? Math.max(0, Math.min(3, saved.step))
    : 0;
  let busy = false;
  const titles = [
    "What should we call you?",
    "What’s your background?",
    "Which model would you like to use?",
    "Your code, ready to explore.",
  ];
  const persist = () => {
    try {
      sessionStorage.setItem(draftKey, JSON.stringify({ ...draft, step }));
    } catch {}
  };
  function capture() {
    for (const key of ["name", "role", "model"]) {
      const input = container.querySelector(`[name="${key}"]`);
      if (input) draft[key] = input.value;
    }
    const maps = container.querySelector('[name="map_now"]');
    if (maps) draft.map_now = maps.checked;
    persist();
  }
  const folder =
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M2.5 6V4.5h5l2 2h8v9h-15z"/></svg>';
  function repositories() {
    const repos = getRepos();
    return repos.length
      ? `<div class="onboarding-repos">${repos.map((repo) => `<div class="onboarding-repo">${folder}<div><strong>${escape(repo.name)}</strong><span title="${escape(repo.path)}">${escape(repo.path.split("/").filter(Boolean).slice(-2).join("/"))}</span></div><span class="connected-mark" aria-label="Connected">✓</span></div>`).join("")}</div>`
      : `<div class="onboarding-connect"><p>Choose repositories in your terminal. This page updates when you’re done.</p><div class="setup-command"><code>scire setup</code><button type="button" id="onboarding-copy">Copy command</button></div></div>`;
  }
  function bindCopy() {
    const copy = container.querySelector("#onboarding-copy");
    if (copy)
      copy.onclick = async () => {
        try {
          await navigator.clipboard.writeText("scire setup");
          copy.textContent = "Copied";
        } catch {
          copy.textContent = "Run scire setup";
        }
      };
  }
  function update(repos, nextProfile) {
    const field = container.querySelector('.model-picker[data-name="model"]');
    if (!draft.model && nextProfile.model && !field?.dataset.edited) {
      draft.model = nextProfile.model;
      field?.setModel(draft.model);
      persist();
    }
    if (step === 3) {
      container.querySelector("#onboarding-title").textContent = repos.length
        ? titles[3]
        : "Connect your first repository.";
      container.querySelector("#onboarding-repositories").innerHTML =
        repositories();
      container.querySelector("#onboarding-next").disabled =
        busy || !repos.length;
      bindCopy();
    }
  }
  async function advance(event) {
    event?.preventDefault();
    if (busy) return;
    const form = container.querySelector("form");
    if (!form.reportValidity()) return;
    capture();
    if (step === 0 && !draft.name.trim()) {
      const name = form.elements.name;
      name.setCustomValidity("What should we call you?");
      name.reportValidity();
      return;
    }
    if (step < 3) {
      step++;
      persist();
      render();
      return;
    }
    if (!draft.name.trim()) {
      step = 0;
      persist();
      render();
      return;
    }
    if (!/^[\w.-]+\/[^\s]+$/.test(draft.model)) {
      step = 2;
      persist();
      render();
      return;
    }
    if (!getRepos().length) return;
    busy = true;
    const next = container.querySelector("#onboarding-next");
    next.disabled = true;
    next.textContent = "Opening…";
    container.querySelector("#onboarding-back").disabled = true;
    try {
      await complete({
        ...draft,
        name: draft.name.trim(),
        role: draft.role.trim(),
      });
      try {
        sessionStorage.removeItem(draftKey);
      } catch {}
    } catch (error) {
      const message = container.querySelector("#onboarding-error");
      message.textContent = error.message;
      message.hidden = false;
      busy = false;
      next.disabled = false;
      next.textContent = "Open workspace";
      container.querySelector("#onboarding-back").disabled = false;
    }
  }
  function render() {
    const mac = /Mac|iPhone|iPad/.test(navigator.platform);
    const hint =
      step === 1 || step === 2 ? `${mac ? "⌘" : "Ctrl"} + Enter` : "Enter";
    const fields = [
      `<label class="sr-only" for="onboarding-name">Your name</label><input class="onboarding-answer" id="onboarding-name" name="name" autocomplete="given-name" maxlength="80" required placeholder="Your first name" value="${escape(draft.name)}">`,
      `<label class="sr-only" for="onboarding-role">Your background</label><textarea class="onboarding-answer" id="onboarding-role" name="role" maxlength="2000" rows="2" placeholder="e.g. Backend engineer, new to this repo">${escape(draft.role)}</textarea><div class="experience-options" role="group" aria-label="Starting points">${["New to this codebase", "Know the basics", "Work here regularly"].map((text) => `<button type="button" data-experience="${text}" aria-pressed="${draft.role === text}">${text}</button>`).join("")}</div>`,
      `${modelPicker("model", "Teaching model", false, draft.model)}<details class="onboarding-provider-help"><summary>Need to connect a provider?</summary><p>Run <code>scire setup --connect</code> in your terminal, then choose your model here.</p></details>`,
      `<div id="onboarding-repositories">${repositories()}</div><label class="onboarding-map-option"><input type="checkbox" name="map_now" ${draft.map_now ? "checked" : ""}><span>Prepare codebase maps<small>Runs in the background using your selected model.</small></span></label>`,
    ][step];
    container.innerHTML = `<div class="onboarding"><form id="onboarding-form"><div class="onboarding-question" data-step="${step}"><h1 id="onboarding-title">${step === 3 && !getRepos().length ? "Connect your first repository." : titles[step]}</h1><div class="onboarding-fields">${fields}</div><p id="onboarding-error" class="onboarding-error" role="alert" hidden></p><div class="onboarding-actions"><button class="primary" id="onboarding-next" type="submit" ${step === 3 && !getRepos().length ? "disabled" : ""}>${step === 3 ? "Open workspace" : "Continue"}<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M3 10h13m-5-5 5 5-5 5"/></svg></button>${step === 1 ? '<button type="button" class="onboarding-skip">Skip for now</button>' : ""}<span class="onboarding-key-hint">press <kbd>${hint}</kbd></span></div></div><div class="onboarding-footer"><button type="button" id="onboarding-back" ${step === 0 ? "disabled" : ""}><span aria-hidden="true">←</span> Back</button><div class="onboarding-progress" role="progressbar" aria-label="Setup progress" aria-valuemin="1" aria-valuemax="4" aria-valuenow="${step + 1}"><span>${step + 1} of 4</span><div>${[0, 1, 2, 3].map((index) => `<i class="${index <= step ? "complete" : ""}"></i>`).join("")}</div></div></div></form></div>`;
    const form = container.querySelector("form");
    form.onsubmit = advance;
    form.addEventListener("input", (event) => {
      if (event.target.name === "name") event.target.setCustomValidity("");
      capture();
    });
    form.addEventListener("change", capture);
    form.onkeydown = (event) => {
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        advance();
      }
    };
    container.querySelector("#onboarding-back").onclick = () => {
      capture();
      step--;
      persist();
      render();
    };
    const skip = container.querySelector(".onboarding-skip");
    if (skip)
      skip.onclick = () => {
        draft.role = "";
        step++;
        persist();
        render();
      };
    container.querySelectorAll("[data-experience]").forEach((button) => {
      button.onclick = () => {
        const input = form.elements.role;
        input.value = button.dataset.experience;
        container
          .querySelectorAll("[data-experience]")
          .forEach((choice) =>
            choice.setAttribute("aria-pressed", String(choice === button)),
          );
        capture();
        input.focus();
      };
    });
    if (step === 2) bindModels();
    bindCopy();
    persist();
    requestAnimationFrame(() => {
      const focus = container.querySelector(
        ".onboarding-answer, #model-provider, #onboarding-next",
      );
      focus?.focus({ preventScroll: true });
    });
  }
  render();
  return { update };
}
