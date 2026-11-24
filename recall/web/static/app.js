// Recall Monitor: live filters, live product check, the source switch, and the toast.
(() => {
  "use strict";
  const fold = (s) => s.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // ---------------------------------------------------------------- toast
  const toast = document.querySelector(".toast");
  if (toast) {
    setTimeout(() => toast.classList.add("is-gone"), 5000);
    const url = new URL(location.href);
    if (url.searchParams.has("msg")) { url.searchParams.delete("msg"); history.replaceState(null, "", url); }
  }

  // ---------------------------------------------------------- recall list
  const rows = [...document.querySelectorAll(".recalls tbody tr")];
  if (rows.length) {
    const q = document.getElementById("q");
    const state = document.getElementById("state");
    const chips = [...document.querySelectorAll(".chip[data-reason]")];
    const count = document.getElementById("recall-count");
    const none = document.getElementById("no-results");
    let reason = "";

    const apply = () => {
      const words = fold(q.value).split(/\s+/).filter(Boolean);
      let shown = 0;
      for (const row of rows) {
        const ok = (!reason || row.dataset.reason === reason)
          && (!state.value || row.dataset.states.split("|").includes(state.value))
          && words.every((w) => row.dataset.search.includes(w));
        row.hidden = !ok;
        shown += ok;
      }
      count.textContent = shown === rows.length ? `${rows.length} notices` : `Showing ${shown} of ${rows.length} notices`;
      none.hidden = shown > 0;
    };
    chips.forEach((chip) => chip.addEventListener("click", () => {
      reason = chip.dataset.reason;
      chips.forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
      apply();
    }));
    q.addEventListener("input", apply);
    state.addEventListener("change", apply);
    document.getElementById("reset").addEventListener("click", () => {
      q.value = ""; state.value = ""; reason = "";
      chips.forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.reason === "")));
      apply();
    });
  }

  // ----------------------------------------------------------- live check
  const check = document.getElementById("check");
  if (check) {
    const out = document.getElementById("check-results");
    let timer = 0;
    let latest = 0;
    const codes = (label, values) => values && values.length
      ? `<div><dt>${label}</dt><dd>${values.map((v) => `<span class="code">${esc(v)}</span>`).join("")}</dd></div>` : "";
    const render = (matches, name) => {
      if (!matches.length) {
        out.innerHTML = `<p class="result__none">No current recall matches “${esc(name)}”.</p>`;
        return;
      }
      out.innerHTML = matches.map((m) => `
        <article class="result result--${m.verdict}">
          <div>
            ${m.level === "possible" ? '<span class="tag tag--possible">Possible match</span> ' : ""}
            <a class="result__title" href="/recall/${encodeURIComponent(m.notice_id)}">${esc(m.title)}</a>
            <div class="hint">${esc(m.reason_label)}, published ${esc(m.date_display)}</div>
          </div>
          <span class="verdict verdict--${m.verdict} verdict--small">${esc(m.verdict_label)}</span>
          ${m.batch.length || m.best_before.length || m.ean.length
            ? `<dl class="pack">${codes("Best before", m.best_before)}${codes("Batch", m.batch)}${codes("EAN", m.ean)}</dl>`
            : '<p class="pack pack--none">The notice names no batch, date or barcode, so every pack counts.</p>'}
          <span class="why">Matched by ${esc(m.match_reason)}</span>
        </article>`).join("");
    };
    const run = async () => {
      const data = new FormData(check);
      const name = String(data.get("name") || "").trim();
      const ean = String(data.get("ean") || "").replace(/\D/g, "");
      if (name.length < 3 && ean.length < 8) { out.innerHTML = ""; return; }
      const id = ++latest;
      const response = await fetch(`/api/check?${new URLSearchParams(data)}`);
      if (!response.ok || id !== latest) return;
      render((await response.json()).matches, name || ean);
    };
    check.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 220); });
  }

  // ------------------------------------------------------- source switch
  const toggle = document.getElementById("show-sources");
  if (toggle) {
    const table = document.getElementById("fields");
    toggle.addEventListener("click", () => {
      const on = toggle.getAttribute("aria-checked") !== "true";
      toggle.setAttribute("aria-checked", String(on));
      toggle.querySelector(".switch__state").textContent = on ? "ON" : "OFF";
      table.classList.toggle("show-detail", on);
    });
  }
})();
