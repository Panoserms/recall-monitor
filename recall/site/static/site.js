// Recall Monitor, public site: your product list lives in this browser (localStorage) and is matched
// here with match.js. Nothing about you is sent anywhere.
(() => {
  "use strict";
  const root = document.body.dataset.root || "";
  const page = document.body.dataset.page;
  const M = window.RecallMatch;
  const KEY = "recall-monitor:products:v1";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fold = (s) => s.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss");
  const FIELDS = ["name", "brand", "ean", "batch", "best_before"];
  const EXAMPLE = [
    { name: "Zauberfleks Schoko", brand: "Kölln" }, { name: "Haferflocken kernig", brand: "Kölln" },
    { name: "Spinat gehackt", brand: "K-Classic", best_before: "31.10.2027" }, { name: "Himbeeren tiefgefroren", brand: "Gut & Günstig" },
    { name: "Pinienkerne", brand: "Alnatura", best_before: "15.06.2027" }, { name: "Vollmilch", brand: "Weihenstephan" },
    { name: "Spaghetti", brand: "Barilla" }, { name: "Hackfleisch vom Rind" }, { name: "Gouda jung", brand: "Milbona" }, { name: "Erdnüsse" },
  ];
  const VERDICT = { affected: "Your pack is affected", not_affected: "Your pack is not affected", check: "Check your pack" };

  // ---------------------------------------------------------------- storage
  let memory = null; // used when the browser refuses localStorage
  function load() {
    if (memory) return memory;
    try { return (JSON.parse(localStorage.getItem(KEY) || "[]") || []).filter((p) => p && p.name); } catch { memory = []; return memory; }
  }
  function save(list) {
    const clean = list.map((p) => Object.fromEntries(FIELDS.map((f) => [f, String(p[f] ?? "").trim()])));
    try { localStorage.setItem(KEY, JSON.stringify(clean)); memory = null; } catch { memory = clean; showStorageWarning(); }
    updateCount();
    return clean;
  }
  function showStorageWarning() { const w = document.getElementById("storage-warning"); if (w) w.hidden = false; }
  function updateCount() { document.querySelectorAll("[data-product-count]").forEach((el) => { el.textContent = load().length; }); }

  // ------------------------------------------------------------------ toast
  const toastEl = document.getElementById("toast");
  let toastTimer = 0;
  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.remove("is-gone");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.add("is-gone"), 4500);
  }

  // ------------------------------------------------------------------- data
  let data = null;
  async function recalls() {
    if (!data) {
      const [r, l] = await Promise.all([fetch(`${root}data/recalls.json`), fetch(`${root}data/lexicon.json`)]);
      if (!r.ok || !l.ok) throw new Error("data missing");
      const json = await r.json();
      const lexicon = await l.json();
      M.init(lexicon);
      if (window.RecallReceipt) window.RecallReceipt.init(lexicon);
      data = { list: json.recalls, byId: new Map(json.recalls.map((x) => [x.id, x])), lexicon };
    }
    return data;
  }
  const matchesFor = async (products) => { const d = await recalls(); return M.findMatches(products, d.list).map((m) => ({ ...m, record: d.byId.get(m.notice_id) })); };

  // -------------------------------------------------------------- rendering
  const codes = (label, values) => (values && values.length
    ? `<div><dt>${label}</dt><dd>${values.map((v) => `<span class="code">${esc(v)}</span>`).join("")}</dd></div>` : "");
  function pack(r) {
    if (!r.batch.length && !r.best_before.length && !r.ean.length) return '<p class="pack pack--none">The notice names no batch, date or barcode, so every pack counts.</p>';
    return `<dl class="pack">${codes("Best before", r.best_before.map(M.showDate))}${codes("Batch", r.batch)}${codes("EAN", r.ean)}</dl>`;
  }
  const recallUrl = (id) => `${root}recall/${encodeURIComponent(id)}.html`;
  // Where the recalled product was sold, as on the recall pages (templates/_shops.html)
  function shopChip(name) {
    const slug = data && data.lexicon.shop_styles ? data.lexicon.shop_styles[name] : "";
    return `<span class="shop-chip${slug ? ` shop--${slug}` : ""}">${esc(name)}</span>`;
  }
  const shops = (sellers) => (sellers && sellers.length
    ? `<p class="shops"><span class="shops__label">Sold at</span> ${sellers.map(shopChip).join(" ")}</p>`
    : '<p class="shops"><span class="shops__none">Shop not named in the notice</span></p>');
  function alertCard(m) {
    const r = m.record, v = m.identifiers.verdict, p = m.product;
    return `<article class="alert alert--${v}${m.level === "possible" ? " alert--possible" : ""}">
      <p class="alert__mine">${m.level === "possible" ? '<span class="tag tag--possible">Possible match</span> ' : ""}Your product: <strong>${esc(p.name)}</strong>${p.brand ? ` (${esc(p.brand)})` : ""}</p>
      <h3 class="alert__title"><a href="${recallUrl(r.id)}">${esc(r.title)}</a></h3>
      ${shops(r.sellers)}
      <p class="alert__reason"><span class="tag tag--${r.is_pathogen ? "pathogen" : "reason"}">${esc(r.reason_label)}</span> <span lang="de">${esc(r.reason_text)}</span></p>
      <p class="verdict verdict--${v}">${VERDICT[v]}</p>
      ${pack(r)}
      ${r.what_to_do ? `<p class="alert__todo"><strong>What to do.</strong> <span lang="de">${esc(r.what_to_do)}</span></p>` : ""}
      <p class="alert__links"><a href="${recallUrl(r.id)}">Details and official notice</a><span class="why">Matched by ${esc(m.reason)}</span></p>
    </article>`;
  }

  // ------------------------------------------------------------ home: alerts
  async function renderMine() {
    const box = document.getElementById("mine");
    if (!box) return;
    const products = load();
    if (!products.length) return; // the page's own empty state stays
    const all = await matchesFor(products);
    const strong = all.filter((m) => m.level === "match");
    const possible = all.filter((m) => m.level === "possible");
    const hitRows = new Set(strong.map((m) => m.product.row));
    const n = products.length, k = hitRows.size, s = n === 1 ? "" : "s";
    const total = data.list.length;
    let html = k
      ? `<h1 id="mine-title" class="lead lead--warn">${k} of your ${n} product${s} ${k === 1 ? "has" : "have"} a current recall</h1><div class="alerts">${strong.map(alertCard).join("")}</div>`
      : `<h1 id="mine-title" class="lead lead--safe">None of your ${n} product${s} ${n === 1 ? "has" : "have"} a current recall</h1><p class="lead__sub">Checked against ${total} current recalls. <a href="${root}products.html">Edit your list</a></p>`;
    if (possible.length) {
      html += `<details class="possible"${k ? "" : " open"}><summary>${possible.length} possible match${possible.length === 1 ? "" : "es"}: similar name, brand unclear</summary><div class="alerts">${possible.map(alertCard).join("")}</div></details>`;
    }
    box.innerHTML = html;
  }

  // ------------------------------------------------------- home: live check
  function setupCheck() {
    const form = document.getElementById("check");
    if (!form) return;
    const out = document.getElementById("check-results");
    let timer = 0;
    const read = () => Object.fromEntries(FIELDS.map((f) => [f, form.elements[f] ? form.elements[f].value.trim() : ""]));
    const run = async () => {
      const product = read();
      const ean = product.ean.replace(/\D/g, "");
      if (product.name.length < 3 && ean.length < 8) { out.innerHTML = ""; return; }
      const found = (await matchesFor([product])).slice(0, 8);
      out.innerHTML = found.length ? found.map((m) => `
        <article class="result result--${m.identifiers.verdict}">
          <div>${m.level === "possible" ? '<span class="tag tag--possible">Possible match</span> ' : ""}
            <a class="result__title" href="${recallUrl(m.notice_id)}">${esc(m.title)}</a>
            <div class="hint">${esc(m.record.reason_label)}, published ${esc(m.record.date_display)}</div></div>
          <span class="verdict verdict--${m.identifiers.verdict} verdict--small">${VERDICT[m.identifiers.verdict]}</span>
          ${pack(m.record)}
          <span class="why">Matched by ${esc(m.reason)}</span>
        </article>`).join("") : `<p class="result__none">No current recall matches “${esc(product.name || product.ean)}”.</p>`;
    };
    form.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 200); });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const product = read();
      if (product.name.length < 3) { form.elements.name.focus(); return; }
      save([...load(), product]);
      form.reset(); out.innerHTML = "";
      toast(`Added ${product.name} to your products.`);
      renderMine();
    });
  }

  // ----------------------------------------------------- home: recall filters
  function setupFilters() {
    const rows = [...document.querySelectorAll(".recalls tbody tr")];
    if (!rows.length) return;
    const q = document.getElementById("q"), state = document.getElementById("state");
    const chips = [...document.querySelectorAll(".chip[data-reason]")];
    const count = document.getElementById("recall-count"), none = document.getElementById("no-results");
    let reason = "";
    const apply = () => {
      const words = fold(q.value).split(/\s+/).filter(Boolean);
      let shown = 0;
      for (const row of rows) {
        const ok = (!reason || row.dataset.reason === reason) && (!state.value || row.dataset.states.split("|").includes(state.value))
          && words.every((w) => row.dataset.search.includes(w));
        row.hidden = !ok; shown += ok;
      }
      count.textContent = shown === rows.length ? `${rows.length} notices` : `Showing ${shown} of ${rows.length} notices`;
      none.hidden = shown > 0;
    };
    chips.forEach((chip) => chip.addEventListener("click", () => {
      reason = chip.dataset.reason; chips.forEach((c) => c.setAttribute("aria-pressed", String(c === chip))); apply();
    }));
    q.addEventListener("input", apply);
    state.addEventListener("change", apply);
    document.getElementById("reset").addEventListener("click", () => {
      q.value = ""; state.value = ""; reason = "";
      chips.forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.reason === ""))); apply();
    });
  }

  // ------------------------------------------------------------ products page
  async function renderProducts() {
    const body = document.getElementById("products-body");
    if (!body) return;
    const products = load();
    document.getElementById("products-empty").hidden = products.length > 0;
    document.getElementById("products-table").hidden = products.length === 0;
    const all = products.length ? await matchesFor(products) : [];
    body.innerHTML = products.map((p, i) => {
      const hits = all.filter((m) => m.product.row === i + 1);
      const status = hits.length ? hits.map((m) => `<a class="verdict verdict--${m.identifiers.verdict} verdict--small" href="${recallUrl(m.notice_id)}" title="${esc(m.title)}">${m.level === "possible" ? "Possible: " : ""}${VERDICT[m.identifiers.verdict]}</a>`).join("")
        : '<span class="verdict verdict--clear verdict--small">No recall</span>';
      const code = (v) => (v ? `<span class="code code--small">${esc(v)}</span>` : "");
      return `<tr><td><strong>${esc(p.name)}</strong>${p.brand ? `<span class="list__company">${esc(p.brand)}</span>` : ""}</td>
        <td>${code(p.best_before)}</td><td>${code(p.batch)}</td><td>${code(p.ean)}</td><td>${status}</td>
        <td><div class="products__actions"><button class="button button--small button--quiet" type="button" data-edit="${i}">Edit</button>
        <button class="button button--small button--danger" type="button" data-remove="${i}" aria-label="Remove ${esc(p.name)}">Remove</button></div></td></tr>`;
    }).join("");
  }

  function setupProducts() {
    const form = document.getElementById("product-form");
    if (!form) return;
    const submit = form.querySelector("[data-submit]"), cancel = form.querySelector("[data-cancel]");
    const reset = () => { form.reset(); form.elements.row.value = ""; submit.textContent = "Add product"; cancel.hidden = true; };
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const product = Object.fromEntries(FIELDS.map((f) => [f, form.elements[f].value.trim()]));
      if (!product.name) { form.elements.name.focus(); return; }
      const list = load();
      const row = form.elements.row.value;
      if (row !== "") { list[+row] = product; save(list); toast(`Saved ${product.name}.`); }
      else { save([...list, product]); toast(`Added ${product.name}.`); }
      reset(); renderProducts(); form.elements.name.focus();
    });
    cancel.addEventListener("click", reset);
    document.getElementById("products-body").addEventListener("click", (event) => {
      const edit = event.target.closest("[data-edit]"), remove = event.target.closest("[data-remove]");
      const list = load();
      if (edit) {
        const p = list[+edit.dataset.edit];
        FIELDS.forEach((f) => { form.elements[f].value = p[f] || ""; });
        form.elements.row.value = edit.dataset.edit; submit.textContent = "Save changes"; cancel.hidden = false;
        form.scrollIntoView({ behavior: "smooth", block: "start" }); form.elements.name.focus();
      }
      if (remove) {
        const [gone] = list.splice(+remove.dataset.remove, 1);
        save(list); renderProducts(); toast(`Removed ${gone.name}.`);
      }
    });
    document.getElementById("export").addEventListener("click", () => {
      const cell = (v) => (/[",\n;]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
      const csv = [FIELDS.join(","), ...load().map((p) => FIELDS.map((f) => cell(p[f] || "")).join(","))].join("\n") + "\n";
      const link = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "my_products.csv" });
      link.click(); URL.revokeObjectURL(link.href);
    });
    document.getElementById("import").addEventListener("change", async (event) => {
      const file = event.target.files[0];
      if (!file) return;
      const added = parseCsv(await file.text());
      save([...load(), ...added]); renderProducts();
      toast(added.length ? `Loaded ${added.length} products from ${file.name}.` : `${file.name} has no column "name".`);
      event.target.value = "";
    });
    document.getElementById("clear").addEventListener("click", () => {
      const before = load();
      if (!before.length) return;
      save([]); renderProducts();
      toast(`Deleted your list of ${before.length} products.`);
    });
  }

  function parseCsv(text) {
    const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
    if (!lines.length) return [];
    const sep = (lines[0].match(/;/g) || []).length > (lines[0].match(/,/g) || []).length ? ";" : ",";
    const split = (line) => {
      const cells = []; let cur = "", quoted = false;
      for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (quoted) { if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') quoted = false; else cur += ch; }
        else if (ch === '"') quoted = true; else if (ch === sep) { cells.push(cur); cur = ""; } else cur += ch;
      }
      cells.push(cur); return cells.map((c) => c.trim());
    };
    const head = split(lines[0]).map((h) => h.toLowerCase());
    if (!head.includes("name")) return [];
    return lines.slice(1).map((line) => { const cells = split(line); return Object.fromEntries(FIELDS.map((f) => [f, cells[head.indexOf(f)] || ""])); })
      .filter((p) => p.name);
  }

  // ------------------------------------------------------------ recall page
  async function renderVerdicts() {
    const box = document.getElementById("my-verdicts");
    const notice = document.querySelector("[data-notice]");
    if (!box || !notice) return;
    const products = load();
    if (!products.length) return;
    const mine = (await matchesFor(products)).filter((m) => m.notice_id === notice.dataset.notice);
    box.innerHTML = mine.map((m) => `<p class="verdict verdict--${m.identifiers.verdict}">${esc(m.product.name)}${m.product.brand ? ` (${esc(m.product.brand)})` : ""}: ${VERDICT[m.identifiers.verdict].toLowerCase()}</p>`).join("");
  }

  function setupSwitch() {
    const toggle = document.getElementById("show-sources");
    if (!toggle) return;
    toggle.addEventListener("click", () => {
      const on = toggle.getAttribute("aria-checked") !== "true";
      toggle.setAttribute("aria-checked", String(on));
      toggle.querySelector(".switch__state").textContent = on ? "ON" : "OFF";
      document.getElementById("fields").classList.toggle("show-detail", on);
    });
  }

  // what the receipt page (receipt-page.js) shares with this file
  window.RecallSite = { root, esc, recalls, pack, recallUrl, toast, load, save, FIELDS, shops, shopChip, lexicon: () => (data ? data.lexicon.retailers || [] : []) };

  // -------------------------------------------------------------------- start
  document.querySelectorAll("[data-load-example]").forEach((button) => button.addEventListener("click", () => {
    if (load().length) { toast("Your list is not empty, so the example list was not loaded."); return; }
    save(EXAMPLE); toast("Loaded the example list. Change it on My products.");
    renderMine(); renderProducts();
  }));
  updateCount();
  setupFilters(); setupCheck(); setupProducts(); setupSwitch();
  const fail = () => toast("The recall data could not be loaded. Reload the page.");
  if (page === "recalls") renderMine().catch(fail);
  if (page === "products") renderProducts().catch(fail);
  if (page === "recall") renderVerdicts().catch(fail);
})();
