// ProfSearch shortlist — client-side only, stored in localStorage.
// No accounts, no server state, no telemetry.

(function () {
  const STORAGE_KEY = "profsearch.shortlist.v1";
  const MAX_COMPARE = 4;

  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_e) {
      return [];
    }
  }

  function save(items) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    } catch (_e) {
      /* quota or private-mode — silent no-op */
    }
  }

  function has(id) {
    return load().some((item) => item.id === id);
  }

  function add(item) {
    const items = load();
    if (items.some((existing) => existing.id === item.id)) return items;
    items.push({
      id: item.id,
      name: item.name || "",
      university: item.university || "",
      department: item.department || "",
      profile_url: item.profile_url || "",
      added_at: new Date().toISOString(),
    });
    save(items);
    return items;
  }

  function remove(id) {
    const items = load().filter((item) => item.id !== id);
    save(items);
    return items;
  }

  function toggle(item) {
    return has(item.id) ? remove(item.id) : add(item);
  }

  function csvEscape(value) {
    const str = String(value == null ? "" : value);
    if (str.includes(",") || str.includes('"') || str.includes("\n")) {
      return '"' + str.replace(/"/g, '""') + '"';
    }
    return str;
  }

  function exportCsv() {
    const items = load();
    const header = ["id", "name", "university", "department", "profile_url", "added_at"];
    const lines = [header.join(",")];
    for (const item of items) {
      lines.push(header.map((k) => csvEscape(item[k])).join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "profsearch-shortlist.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function renderPanel() {
    const panel = document.getElementById("shortlist-panel");
    if (!panel) return;
    const items = load();
    const body = panel.querySelector("[data-shortlist-body]");
    const count = panel.querySelector("[data-shortlist-count]");
    if (count) count.textContent = String(items.length);

    if (!body) return;
    if (items.length === 0) {
      body.innerHTML = '<div class="shortlist-empty">Click ★ on any result to save it here. Data stays in your browser.</div>';
      return;
    }
    body.innerHTML = items
      .map(
        (item) =>
          `<div class="shortlist-row">
             <a class="shortlist-name" href="/professor/${item.id}">${escapeHtml(item.name)}</a>
             <span class="shortlist-uni">${escapeHtml(item.university)}</span>
             <button class="shortlist-x" type="button" data-shortlist-remove="${item.id}" aria-label="Remove">×</button>
           </div>`
      )
      .join("");
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function compareUrl() {
    const items = load().slice(0, MAX_COMPARE);
    if (items.length === 0) return "/compare";
    return "/compare?ids=" + items.map((i) => i.id).join(",");
  }

  function syncCardButtons() {
    document.querySelectorAll("[data-shortlist-toggle]").forEach((el) => {
      const id = Number(el.getAttribute("data-shortlist-toggle"));
      const saved = has(id);
      el.setAttribute("aria-pressed", saved ? "true" : "false");
      el.classList.toggle("is-saved", saved);
      const label = el.querySelector("[data-shortlist-label]");
      if (label) label.textContent = saved ? "Saved" : "Save";
    });
  }

  function handleClick(e) {
    const toggleEl = e.target.closest("[data-shortlist-toggle]");
    if (toggleEl) {
      e.preventDefault();
      const id = Number(toggleEl.getAttribute("data-shortlist-toggle"));
      toggle({
        id,
        name: toggleEl.getAttribute("data-name") || "",
        university: toggleEl.getAttribute("data-university") || "",
        department: toggleEl.getAttribute("data-department") || "",
        profile_url: toggleEl.getAttribute("data-profile") || "",
      });
      syncCardButtons();
      renderPanel();
      return;
    }
    const removeEl = e.target.closest("[data-shortlist-remove]");
    if (removeEl) {
      e.preventDefault();
      const id = Number(removeEl.getAttribute("data-shortlist-remove"));
      remove(id);
      syncCardButtons();
      renderPanel();
      const row = removeEl.closest(".compare-col");
      if (row) row.remove();
      return;
    }
    if (e.target.closest("[data-shortlist-export]")) {
      e.preventDefault();
      exportCsv();
      return;
    }
    if (e.target.closest("[data-shortlist-compare]")) {
      var url = compareUrl();
      htmx.ajax("GET", url, { target: "main", select: "main", swap: "innerHTML" });
      window.history.pushState({}, "", url);
    }
  }

  function init() {
    renderPanel();
    syncCardButtons();
    document.addEventListener("click", handleClick);
    document.body.addEventListener("htmx:afterSettle", syncCardButtons);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
