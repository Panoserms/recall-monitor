// Recall Monitor, "Check a receipt": the receipt is read, shown for correction and matched in this browser.
// Nothing is uploaded. The receipt lives in the page's memory only and is gone after a reload.
// Reading: receipt.js (text), vendor/pdfjs (PDF with a text layer), vendor/tesseract (pictures; loaded only when needed).
(() => {
  "use strict";
  const S = window.RecallSite, R = window.RecallReceipt;
  if (!S || !R || document.body.dataset.page !== "receipt") return;
  const { esc, root } = S;
  const $ = (id) => document.getElementById(id);
  const money = (n) => (n === null || n === undefined ? "" : n.toFixed(2).replace(".", ","));
  const germanDate = (iso) => (iso ? iso.split("-").reverse().join(".") : "");

  let lines = [];      // { id, printed, text, initial, keep, price, nonfood }
  let meta = null;     // what the reader found: layout, total, sums, skipped lines, how it was read
  let nextId = 1, resultsShown = false, timer = 0;

  const status = (text, failed = false) => { const el = $("read-status"); el.textContent = text; el.classList.toggle("receipt-status--failed", failed); };

  // ---------------------------------------------------------------- reading
  class Unreadable extends Error {}

  async function readFile(file) {
    const name = file.name.toLowerCase();
    if (file.type === "application/pdf" || name.endsWith(".pdf")) return readPdf(file);
    if (file.type.startsWith("text/") || name.endsWith(".txt")) return { text: await file.text(), how: "text" };
    if (file.type.startsWith("image/") || /\.(jpe?g|png|webp|gif|bmp|heic|heif|avif)$/.test(name)) return { text: await readPicture(file, name), how: "picture" };
    throw new Unreadable(`“${file.name}” is not a text file, a PDF or a picture.`);
  }

  // PDF: lines are rebuilt from the positions of the text pieces, so columns stay apart.
  async function readPdf(file) {
    status("Reading the PDF on this device …");
    const vendor = new URL(`${root}static/vendor/pdfjs/`, location.href).href;
    const pdfjs = await import(`${vendor}pdf.min.mjs`);
    pdfjs.GlobalWorkerOptions.workerSrc = `${vendor}pdf.worker.min.mjs`;
    let pdf;
    try { pdf = await pdfjs.getDocument({ data: await file.arrayBuffer(), isEvalSupported: false }).promise; }
    catch { throw new Unreadable("This PDF could not be opened. If it is protected by a password, save a copy without one."); }
    const out = [];
    for (let n = 1; n <= pdf.numPages; n++) {
      const page = await pdf.getPage(n);
      const pieces = (await page.getTextContent()).items.filter((i) => i.str && i.str.trim());
      const rows = [];
      for (const piece of pieces) {
        const x = piece.transform[4], y = piece.transform[5], size = Math.abs(piece.transform[3]) || 10;
        let row = rows.find((r) => Math.abs(r.y - y) < size * 0.45);
        if (!row) { row = { y, parts: [] }; rows.push(row); }
        row.parts.push({ x, end: x + piece.width, str: piece.str, char: piece.width / Math.max(1, piece.str.length) });
      }
      rows.sort((a, b) => b.y - a.y);
      for (const row of rows) {
        row.parts.sort((a, b) => a.x - b.x);
        let line = "", end = null;
        for (const part of row.parts) {
          if (end !== null) line += " ".repeat(Math.max(1, Math.round((part.x - end) / (part.char || 5))));
          line += part.str; end = part.end;
        }
        out.push(line);
      }
    }
    const text = out.join("\n");
    if (text.replace(/\s/g, "").length >= 20) return { text, how: "pdf" };
    // no text layer: the pages are pictures of a receipt
    const page = await pdf.getPage(1);
    const viewport = page.getViewport({ scale: 2.5 });
    const canvas = Object.assign(document.createElement("canvas"), { width: viewport.width, height: viewport.height });
    await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
    const read = await recognise(canvas);
    canvas.width = canvas.height = 0;
    return { text: read, how: "picture" };
  }

  // Pictures: decoded by the browser, read by Tesseract (WebAssembly, German model), then dropped.
  async function readPicture(file, name) {
    let bitmap;
    try { bitmap = await createImageBitmap(file); }
    catch {
      const heic = /hei[cf]/.test(file.type) || /\.hei[cf]$/.test(name);
      throw new Unreadable(heic
        ? "This browser cannot open HEIC photos (Safari can; Chrome and Edge cannot). Take a screenshot of the photo, or save it as JPG, and add that."
        : "This picture could not be opened. Try a JPG or PNG.");
    }
    const scale = Math.min(1, 2600 / Math.max(bitmap.width, bitmap.height)); // enough for till print, kind to phone memory
    const canvas = Object.assign(document.createElement("canvas"), { width: Math.round(bitmap.width * scale), height: Math.round(bitmap.height * scale) });
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    try { return await recognise(canvas); }
    finally { canvas.width = canvas.height = 0; } // the picture is gone from memory once it is read
  }

  let tesseractLoading = null;
  function loadTesseract() {
    tesseractLoading ||= new Promise((resolve, reject) => {
      const script = Object.assign(document.createElement("script"), { src: `${root}static/vendor/tesseract/tesseract.min.js` });
      script.onload = () => resolve(window.Tesseract);
      script.onerror = () => reject(new Unreadable("The text recognition could not be loaded. Reload the page and try again."));
      document.head.append(script);
    });
    return tesseractLoading;
  }

  async function recognise(canvas) {
    status("Loading the text recognition (about 5 MB, once) …");
    const Tesseract = await loadTesseract();
    const base = new URL(`${root}static/vendor/tesseract/`, location.href).href;
    const worker = await Tesseract.createWorker("deu", 1, {
      workerPath: `${base}worker.min.js`, corePath: `${base}core`, langPath: `${base}lang`, gzip: true, workerBlobURL: false,
      logger: (m) => { if (m.status === "recognizing text") status(`Reading the picture on this device … ${Math.round(m.progress * 100)} %`); },
    });
    try {
      await worker.setParameters({ tessedit_pageseg_mode: "6", preserve_interword_spaces: "1" });
      const { data } = await worker.recognize(canvas);
      return data.text;
    } finally { await worker.terminate(); }
  }

  // ----------------------------------------------------------------- review
  async function take(text, how) {
    await S.recalls(); // loads the recalls and the lexicons the reader needs
    const parsed = R.parse(how === "picture" && R.repairOcr ? R.repairOcr(text) : text);
    const products = parsed.items.filter((i) => i.kind === "product");
    if (!products.length) {
      status(how === "picture" ? "No product lines could be read from this picture. A sharper, straight photo of the whole receipt helps; or paste the text."
        : "No product lines were found in this text.", true);
      return;
    }
    lines = products.map((i) => {
      const spoken = R.phrase(i.description).text;
      return { id: nextId++, printed: i.description, text: spoken, initial: spoken, keep: !i.nonfood, price: i.line_total, nonfood: i.nonfood };
    });
    meta = {
      how, layout: parsed.layout, total: parsed.total, sum: parsed.items_sum, sumsMatch: parsed.sums_match, unparsed: parsed.unparsed,
      deposits: parsed.items.filter((i) => i.kind !== "product").length,
      discounts: parsed.items.reduce((n, i) => n + i.discount_names.length, 0),
    };
    resultsShown = false;
    $("step-results").hidden = true;
    renderReview(parsed.store, parsed.date);
    status(`${lines.length} product line${lines.length === 1 ? "" : "s"} read. Check them below.`);
    $("step-review").hidden = false;
    $("review-title").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }

  function lineHtml(l) {
    const flag = l.nonfood ? "Non-food article, not checked" : l.text !== l.initial ? "Changed by you" : l.printed && l.initial !== l.printed ? "Abbreviation spelt out" : "";
    return `<li class="slip-line${l.keep ? "" : " slip-line--off"}" data-id="${l.id}">
      <label class="slip-line__keep"><input type="checkbox" data-keep ${l.keep ? "checked" : ""}><span class="visually-hidden">Check ${esc(l.printed || l.text || "this line")}</span></label>
      <div class="slip-line__printed">${l.printed ? `<span class="slip-line__text">${esc(l.printed)}</span>` : '<span class="hint">Added by you</span>'}${l.price !== null && l.price !== undefined ? `<span class="slip-line__price">${money(l.price)}</span>` : ""}</div>
      <label class="slip-line__read">Product name<input data-text lang="de" spellcheck="false" value="${esc(l.text)}" placeholder="Type the product name"></label>
      <span class="slip-line__flag" data-flag>${flag}</span>
      <button class="button button--small button--quiet" type="button" data-remove aria-label="Remove ${esc(l.printed || l.text || "this line")}">Remove</button>
    </li>`;
  }

  function renderReview(store, date) {
    const shops = [...new Set((S.lexicon ? S.lexicon() : []).map((row) => row[0]))];
    $("receipt-store").innerHTML = `<option value="">Not sure, or another shop</option>${shops.map((s) => `<option${s === store ? " selected" : ""}>${esc(s)}</option>`).join("")}`;
    $("receipt-date").value = date || "";
    $("example-note").hidden = meta.how !== "example";
    $("layout-note").hidden = meta.layout === "lidl";
    $("ocr-note").hidden = meta.how !== "picture";
    const sum = $("receipt-sum");
    sum.className = "receipt-sum";
    if (meta.sumsMatch === true) sum.textContent = `All lines were read: they add up to the printed total of ${money(meta.total)} €.`;
    else if (meta.sumsMatch === false) {
      sum.textContent = `The lines add up to ${money(meta.sum)} €, but the receipt says ${money(meta.total)} €. A line may be missing or misread.`;
      sum.classList.add("receipt-sum--off");
    } else sum.textContent = meta.layout === "lidl" ? "No total was found on the receipt, so the lines could not be checked against it." : "";
    $("lines").innerHTML = lines.map(lineHtml).join("");
    const skipped = [];
    if (meta.deposits) skipped.push(`${meta.deposits} deposit line${meta.deposits === 1 ? "" : "s"}`);
    if (meta.discounts) skipped.push(`${meta.discounts} discount${meta.discounts === 1 ? "" : "s"}`);
    if (meta.unparsed.length) skipped.push(`${meta.unparsed.length} line${meta.unparsed.length === 1 ? "" : "s"} that could not be read (${meta.unparsed.map((u) => `“${u}”`).join(", ")})`);
    $("skipped").textContent = skipped.length ? `Left out: ${skipped.join(", ")}.` : "";
    updateCheckButton();
  }

  const kept = () => lines.filter((l) => l.keep && l.text.trim());
  function updateCheckButton() {
    const n = kept().length;
    $("check").textContent = n ? `Check ${n} line${n === 1 ? "" : "s"} against the recalls` : "No line to check";
    $("check").disabled = !n;
  }

  // ---------------------------------------------------------------- results
  function resultCard(m, record, line, likely, data) {
    const store = $("receipt-store").value, date = $("receipt-date").value;
    const slug = store && data.lexicon.shop_styles ? data.lexicon.shop_styles[store] || "" : "";
    // the receipt's own shop picks the colour: the card reads as "your Lidl purchase"
    const mine = store
      ? `Your <span class="shop-chip${slug ? ` shop--${slug}` : ""}">${esc(store)}</span> purchase${date ? ` of ${esc(germanDate(date))}` : ""}`
      : `Your purchase${date ? ` of ${esc(germanDate(date))}` : ""}`;
    return `<article class="alert alert--check${likely ? "" : " alert--possible"}${slug ? ` shop-edge shop--${slug}` : ""}" data-result="${esc(m.notice_id)}">
      <p class="alert__mine">${mine}: <strong>${esc(line.printed || line.text)}</strong></p>
      <h3 class="alert__title"><a href="${S.recallUrl(record.id)}">${esc(record.title)}</a></h3>
      ${S.shops(record.sellers)}
      <p class="alert__reason"><span class="tag tag--${record.is_pathogen ? "pathogen" : "reason"}">${esc(record.reason_label)}</span> <span lang="de">${esc(record.reason_text)}</span></p>
      <p class="verdict verdict--check">Possible match: check your pack</p>
      ${S.pack(record)}
      <p class="alert__basis">${m.basis === "name only"
        ? "Matched by name only. A receipt shows no brand, batch or best-before date, so only the pack can tell."
        : "Matched by name and brand. A receipt shows no batch or best-before date, so only the pack can tell."}</p>
      ${likely ? "" : `<p class="alert__less">Less likely: ${esc(m.less_likely.join("; "))}.</p>`}
      <p class="alert__links"><a href="${S.recallUrl(record.id)}">Details and official notice</a>
        <button class="link" type="button" data-save="${line.id}">Add to my products</button>
        <span class="why">Read as “${esc(m.matched_as)}”; ${esc(m.reason)}</span></p>
    </article>`;
  }

  async function check() {
    const data = await S.recalls();
    const checked = kept();
    const byNo = new Map(checked.map((l) => [l.id, l]));
    const items = checked.map((l) => ({
      line_no: l.id, kind: "product", nonfood: false, description: l.printed || l.text,
      ...(l.printed && l.text === l.initial ? {} : { text: l.text.trim() }),
    }));
    const found = R.matchReceipt({ items, store: "", date: "" }, data.list, $("receipt-store").value, $("receipt-date").value);
    const likely = found.filter((m) => !m.less_likely.length), less = found.filter((m) => m.less_likely.length);
    const n = checked.length, hit = new Set(likely.map((m) => m.line_no)).size;
    let html;
    if (hit) {
      html = `<p class="lead lead--check" id="result-lead">${hit} of your ${n} line${n === 1 ? "" : "s"} may be a recalled product</p>
        <p class="lead__sub">Compare the codes below with the print on your pack. Only the pack can tell whether yours is one of the recalled ones.</p>
        <div class="alerts">${likely.map((m) => resultCard(m, data.byId.get(m.notice_id), byNo.get(m.line_no), true, data)).join("")}</div>`;
    } else {
      html = `<p class="lead lead--safe" id="result-lead">None of your ${n} line${n === 1 ? "" : "s"} matches a current recall</p>
        <p class="lead__sub">Checked by product name against ${data.list.length} current recalls. Names on receipts are short, so a recalled product can be missed; the list of all recalls is on the <a href="${root}index.html">start page</a>.</p>`;
    }
    if (less.length) {
      html += `<details class="possible"><summary>${less.length} less likely match${less.length === 1 ? "" : "es"}: the shop or the dates speak against ${less.length === 1 ? "it" : "them"}</summary>
        <div class="alerts">${less.map((m) => resultCard(m, data.byId.get(m.notice_id), byNo.get(m.line_no), false, data)).join("")}</div></details>`;
    }
    $("results").innerHTML = html;
    $("step-results").hidden = false;
    // said once, in words, whenever the result changes (the cards themselves are not read out on every change)
    $("result-status").textContent = `${hit ? `${hit} of your ${n} lines may be a recalled product` : `None of your ${n} lines matches a current recall`}`
      + (less.length ? `, and ${less.length} less likely match${less.length === 1 ? "" : "es"}.` : ".");
    document.dispatchEvent(new CustomEvent("recall:results", { detail: { likely: likely.length, less: less.length, first: !resultsShown } }));
    if (!resultsShown) {
      resultsShown = true;
      $("results-title").focus({ preventScroll: true });
      $("results-title").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    }
  }
  const recheck = () => { if (resultsShown) { clearTimeout(timer); timer = setTimeout(() => check().catch(fail), 250); } };
  const fail = () => S.toast("The recall data could not be loaded. Reload the page.");

  function forget() {
    lines = []; meta = null; resultsShown = false;
    $("receipt-text").value = ""; $("receipt-file").value = ""; $("lines").innerHTML = ""; $("results").innerHTML = "";
    $("step-review").hidden = true; $("step-results").hidden = true;
    status("The receipt is forgotten.");
    $("add-title").scrollIntoView({ block: "start" });
  }

  // ------------------------------------------------------------------ events
  async function addFile(file) {
    if (!file) return;
    try {
      status(`Reading ${file.name} on this device …`);
      const { text, how } = await readFile(file);
      await take(text, how);
    } catch (error) {
      status(error instanceof Unreadable ? error.message : "This file could not be read. Paste the text of the receipt instead.", true);
    } finally { $("receipt-file").value = ""; }
  }
  $("receipt-file").addEventListener("change", (event) => addFile(event.target.files[0]));
  const zone = $("dropzone");
  ["dragenter", "dragover"].forEach((type) => zone.addEventListener(type, (event) => { event.preventDefault(); zone.classList.add("dropzone--over"); }));
  ["dragleave", "drop"].forEach((type) => zone.addEventListener(type, (event) => { event.preventDefault(); zone.classList.remove("dropzone--over"); }));
  zone.addEventListener("drop", (event) => addFile(event.dataTransfer.files[0]));

  $("paste-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = $("receipt-text").value;
    if (!text.trim()) { status("Paste the text of a receipt first.", true); $("receipt-text").focus(); return; }
    take(text, "text").catch(fail);
  });
  $("example").addEventListener("click", async () => {
    try {
      const response = await fetch(`${root}data/example_receipt.txt`);
      if (!response.ok) throw new Error();
      const text = await response.text();
      $("receipt-text").value = text;
      await take(text, "example");
    } catch { fail(); }
  });

  $("lines").addEventListener("input", (event) => {
    const row = event.target.closest("[data-id]"); if (!row) return;
    const line = lines.find((l) => l.id === +row.dataset.id);
    if (event.target.matches("[data-text]")) {
      line.text = event.target.value;
      row.querySelector("[data-flag]").textContent = line.nonfood && !line.keep ? "Non-food article, not checked" : line.text !== line.initial ? "Changed by you" : line.printed && line.initial !== line.printed ? "Abbreviation spelt out" : "";
      row.classList.toggle("slip-line--changed", line.text !== line.initial);
    }
    if (event.target.matches("[data-keep]")) { line.keep = event.target.checked; row.classList.toggle("slip-line--off", !line.keep); }
    updateCheckButton(); recheck();
  });
  $("lines").addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove]"); if (!button) return;
    const row = button.closest("[data-id]");
    const index = lines.findIndex((l) => l.id === +row.dataset.id);
    const [gone] = lines.splice(index, 1);
    const next = row.nextElementSibling || row.previousElementSibling;
    document.dispatchEvent(new CustomEvent("recall:line-removed", { detail: { row } }));
    if (!row.dataset.leaving) row.remove();
    (next ? next.querySelector("[data-text]") : $("add-line")).focus();
    S.toast(`Removed ${gone.printed || gone.text || "the line"}.`);
    updateCheckButton(); recheck();
  });
  $("add-line").addEventListener("click", () => {
    const line = { id: nextId++, printed: "", text: "", initial: "", keep: true, price: null, nonfood: false };
    lines.push(line);
    $("lines").insertAdjacentHTML("beforeend", lineHtml(line));
    const row = $("lines").lastElementChild;
    document.dispatchEvent(new CustomEvent("recall:line-added", { detail: { row } }));
    row.querySelector("[data-text]").focus();
    updateCheckButton();
  });
  $("receipt-store").addEventListener("change", recheck);
  $("receipt-date").addEventListener("change", recheck);
  $("check").addEventListener("click", () => check().catch(fail));
  $("forget").addEventListener("click", forget);
  $("results").addEventListener("click", (event) => {
    const button = event.target.closest("[data-save]"); if (!button) return;
    const line = lines.find((l) => l.id === +button.dataset.save); if (!line) return;
    S.save([...S.load(), { name: line.text.trim() || line.printed, brand: "", ean: "", batch: "", best_before: "" }]);
    button.replaceWith(Object.assign(document.createElement("span"), { className: "hint", textContent: "Added to your products" }));
    S.toast(`Added ${line.text.trim() || line.printed}. On My products you can add its best-before date or batch to learn whether your pack is affected.`);
  });
})();
