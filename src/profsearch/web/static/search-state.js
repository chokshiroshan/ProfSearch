// ProfSearch search-state — persists user state across boosted HTMX navigation.
// Handles: search URL restore, email draft save/restore, nav active highlight.

(function () {
  var SEARCH_KEY = "profsearch.search.url";
  var DRAFT_PREFIX = "profsearch.email-draft.";

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ── Search URL persistence ──

  function saveSearchUrl() {
    var form = document.getElementById("search-form");
    if (!form) return;
    var q = form.querySelector('input[name="q"]');
    if (!q || !q.value.trim()) return;
    var params = new URLSearchParams();
    params.set("q", q.value);
    ["university", "department_type", "verification", "match_status"].forEach(function (name) {
      var hidden = document.getElementById("hf-" + name);
      if (hidden && hidden.value) params.set(name, hidden.value);
    });
    try { sessionStorage.setItem(SEARCH_KEY, "/?" + params.toString()); } catch (_e) {}
  }

  function getSavedSearchUrl() {
    try { return sessionStorage.getItem(SEARCH_KEY); } catch (_e) { return null; }
  }

  // Intercept boosted Search nav link to restore previous search
  document.body.addEventListener("htmx:configRequest", function (e) {
    var elt = e.detail.elt;
    if (!elt || !elt.closest(".topnav-links")) return;
    var href = elt.getAttribute("href");
    if (href === "/") {
      var saved = getSavedSearchUrl();
      if (saved) {
        e.detail.path = saved;
      }
    }
  });

  // Save search URL after HTMX search results load
  document.body.addEventListener("htmx:afterSettle", function () {
    saveSearchUrl();
  });

  // ── Email draft persistence ──

  function saveEmailDraft() {
    var textarea = document.querySelector("[id^='email-draft-body-']");
    if (!textarea) return;
    var pid = textarea.id.replace("email-draft-body-", "");
    var data = { body: textarea.value };
    var fields = {
      interest: "email-interest-",
      name: "email-name-",
      stage: "email-stage-",
      backend: "email-backend-",
      background: "email-bg-"
    };
    Object.keys(fields).forEach(function (key) {
      var el = document.getElementById(fields[key] + pid);
      if (el) data[key] = el.value;
    });
    try { sessionStorage.setItem(DRAFT_PREFIX + pid, JSON.stringify(data)); } catch (_e) {}
  }

  function restoreEmailDraft() {
    // Find any email draft output or form on the page
    var output = document.querySelector("[id^='email-draft-output-']");
    if (!output) return;
    var pid = output.id.replace("email-draft-output-", "");
    var saved;
    try { saved = JSON.parse(sessionStorage.getItem(DRAFT_PREFIX + pid)); } catch (_e) { return; }
    if (!saved) return;

    // Restore form inputs
    var fields = {
      interest: "email-interest-",
      name: "email-name-",
      stage: "email-stage-",
      backend: "email-backend-",
      background: "email-bg-"
    };
    Object.keys(fields).forEach(function (key) {
      var el = document.getElementById(fields[key] + pid);
      if (el && saved[key]) el.value = saved[key];
    });

    // Restore generated draft body if the output container is empty
    if (saved.body && output.children.length === 0) {
      output.innerHTML =
        '<div class="email-draft-result">' +
          '<div class="email-draft-meta"><span class="badge badge-matched">restored draft</span></div>' +
          '<textarea id="email-draft-body-' + pid + '" class="email-draft-body" rows="14" spellcheck="false">' +
            escapeHtml(saved.body) +
          '</textarea>' +
        '</div>';
    } else {
      var existing = document.getElementById("email-draft-body-" + pid);
      if (existing && saved.body && !existing.value) {
        existing.value = saved.body;
      }
    }
  }

  // Save email draft before any boosted navigation
  document.body.addEventListener("htmx:beforeRequest", function (e) {
    var elt = e.detail.elt;
    if (elt && elt.tagName === "A") {
      saveEmailDraft();
      saveSearchUrl();
    }
  });

  // Save email draft on full page navigations (back button, direct URL entry, etc.)
  window.addEventListener("beforeunload", function () {
    saveEmailDraft();
    saveSearchUrl();
  });

  // ── Nav active highlight ──

  function syncNavHighlight() {
    var path = window.location.pathname;
    document.querySelectorAll(".topnav-links a").forEach(function (a) {
      var href = a.getAttribute("href");
      if (href === path || (path.startsWith("/professor") && href === "/") || (path === "/" && href === "/")) {
        a.classList.add("active");
      } else {
        a.classList.remove("active");
      }
    });
  }

  document.body.addEventListener("htmx:afterSettle", function () {
    syncNavHighlight();
    restoreEmailDraft();
  });

  // ── Init ──

  function init() {
    saveSearchUrl();
    syncNavHighlight();
    restoreEmailDraft();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
