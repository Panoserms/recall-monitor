// Receipts in the browser: a line-by-line port of recall/receipt.py, so that a visitor's receipt never
// leaves their device. tests/test_receipt_parity.py runs the same input through Python and this file
// and requires equal answers. Needs match.js (RecallMatch) to be loaded first.
(function (root) {
  "use strict";

  const M = root.RecallMatch;
  const POSSIBLE = 74, CUT_AT = 20, MIN_PREFIX = 4, GRACE_DAYS = 7;
  let RETAILERS = [];   // [shop, spelling, exact]
  let ABBREVIATIONS = {}; // folded abbreviation -> what it stands for

  // --------------------------------------------------------------- parsing
  const ITEM = /^(?<d>\S.*?)\s+(?:(?<u>[0-9]+,[0-9]{2})\s+x\s+(?<q>[0-9]+)\s+)?(?<t>-?[0-9]+,[0-9]{2})\s+(?<tax>[A-Z])\s*$/;
  const DISCOUNT = /^\s*(?<d>\S.*?)\s+(?<t>-[0-9]+,[0-9]{2})\s*$/;
  const WEIGHT = /^\s*(?<kg>[0-9]+,[0-9]{3})\s*kg\s+x\s+(?<ppk>[0-9]+,[0-9]{2})\s+EUR\/kg\s*$/;
  const RETURN = /^\s*(?<q>-?[0-9]+)\s+x\s+(?<u>[0-9]+,[0-9]{2})\s*$/;
  const TOTAL = /^\s*zu zahlen\s+(?<t>-?[0-9.]+,[0-9]{2})\s*$/i;
  const WHEN = /(?<![0-9])([0-9]{2})\.([0-9]{2})\.([0-9]{4}|[0-9]{2})\s+([0-9]{2}):([0-9]{2})(?![0-9])/g;
  const ARTICLE_NUMBER = /[-' ]+[0-9]{6,}\s*$/; // "Trinkflasche-0451849": Lidl's number for non-food articles
  const RULE_LINE = /^[-=_*¦| ]+$/;
  const TAX_TABLE = /MWST|Brutto/i; // "MWST% MWST + Netto = Brutto": the column "Netto" is not the shop Netto
  const PRICE_TAIL = /(?:\s+(?:[0-9]+\s*x\s*)?-?[0-9]+[.,][0-9]{2}(?:\s*(?:€|EUR))?(?:\s+[A-Z0-9])?)+\s*$/;
  const NOT_A_PRODUCT = new RegExp("^\\s*(?:summe|zwischensumme|gesamt|total|zu zahlen|mwst|ust|steuer|netto|brutto|bar\\b|rückgeld|" +
    "kreditkarte|karte|girocard|ec-|visa|mastercard|pfand|leergut|rabatt|eur\\b|datum|uhrzeit|beleg|bon-|kasse|tel\\b|" +
    "www\\.|vielen dank|danke)", "i");

  function cents(text) {
    const negative = text.startsWith("-");
    const digits = parseInt(text.replace(/^-+/, "").replace(/\./g, "").replace(/,/g, ""), 10);
    return negative ? -digits : digits;
  }

  function item(number, kind, description) {
    return {
      line_no: number, kind, description, nonfood: ARTICLE_NUMBER.test(description), quantity: 1, unit_price: null,
      weight_kg: null, price_per_kg: null, line_total: null, tax: "", discount: 0, discount_names: [],
    };
  }

  const escapeRegExp = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  let retailerPatterns = null;
  function lexiconHits(text) {
    if (!retailerPatterns) {
      retailerPatterns = RETAILERS.map((row, index) => ({ row, index })).sort((a, b) => b.row[1].length - a.row[1].length || a.index - b.index)
        .map(({ row }) => ({ shop: row[0], exact: row[2] === "exact", source: `(?<![\\p{L}\\p{N}_])${escapeRegExp(row[1])}(?![\\p{L}\\p{N}_])` }));
    }
    const hits = [];
    for (const p of retailerPatterns) {
      for (const m of text.matchAll(new RegExp(p.source, p.exact ? "gu" : "giu"))) {
        const start = m.index, end = m.index + m[0].length;
        if (!hits.some((h) => start < h[1] && h[0] < end)) hits.push([start, end, p.shop]);
      }
    }
    return hits.sort((a, b) => a[0] - b[0] || a[1] - b[1] || (a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0));
  }

  function findStore(lines) {
    for (const line of lines) {
      if (TAX_TABLE.test(line)) continue;
      const hits = lexiconHits(line);
      if (hits.length) return hits[0][2];
    }
    return "";
  }

  const pad = (n, width) => String(n).padStart(width, "0");
  function findDate(text) {
    for (const m of String(text).matchAll(WHEN)) {
      const day = +m[1], month = +m[2], year = +m[3] + (m[3].length === 2 ? 2000 : 0);
      if (month >= 1 && month <= 12 && day >= 1 && day <= 31 && year >= 2000 && year <= 2099) return `${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}`;
    }
    return "";
  }

  function parse(text) {
    const lines = String(text).replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/\t/g, "    ").split("\n").map((l) => l.trimEnd());
    let start = lines.findIndex((l) => l.trim() === "EUR") + 1; // -1 + 1 = 0 when there is no such line
    let end = lines.findIndex((l) => TOTAL.test(l));
    if (end === -1) end = lines.length;
    const total = end < lines.length ? cents(TOTAL.exec(lines[end]).groups.t) : null;

    const items = [], unparsed = [], header = lines.slice(0, start);
    let current = null, sum = 0, found;
    for (const line of lines.slice(start, end)) {
      if (!line.trim() || RULE_LINE.test(line)) continue;
      if (current && (found = WEIGHT.exec(line))) {
        current.weight_kg = parseInt(found.groups.kg.replace(",", ""), 10) / 1000;
        current.price_per_kg = cents(found.groups.ppk) / 100;
        continue;
      }
      if (current && (found = RETURN.exec(line))) {
        current.quantity = parseInt(found.groups.q, 10);
        current.unit_price = cents(found.groups.u) / 100;
        continue;
      }
      if ((found = ITEM.exec(line))) {
        const description = found.groups.d.trim();
        const kind = description.startsWith("Pfandrückgabe") ? "deposit_return" : description.startsWith("Pfand") ? "deposit" : "product";
        current = item(items.length + 1, kind, description);
        current.quantity = found.groups.q ? parseInt(found.groups.q, 10) : 1;
        current.unit_price = cents(found.groups.u || found.groups.t) / 100;
        current.line_total = cents(found.groups.t) / 100;
        current.tax = found.groups.tax;
        sum += cents(found.groups.t);
        items.push(current);
        continue;
      }
      if (current && (found = DISCOUNT.exec(line))) {
        current.discount += cents(found.groups.t); // in cents until the end, so the sum stays exact
        current.discount_names.push(found.groups.d.trim());
        sum += cents(found.groups.t);
        continue;
      }
      (current ? unparsed : header).push(line.trim());
    }

    const footer = lines.slice(end);
    if (!items.length) return parseUnknown(lines);
    for (const it of items) it.discount = it.discount / 100;
    const names = items.flatMap((it) => it.discount_names);
    return {
      layout: "lidl", store: findStore([...header, ...names, ...footer]), date: findDate(text),
      total: total === null ? null : total / 100, items_sum: sum / 100, sums_match: total === null ? null : sum === total,
      items, unparsed,
    };
  }

  function parseUnknown(lines) {
    const items = [];
    for (const line of lines) {
      const description = line.replace(PRICE_TAIL, "").trim();
      if ((description.match(/\p{L}/gu) || []).length < 3 || NOT_A_PRODUCT.test(description) || RULE_LINE.test(line)) continue;
      items.push(item(items.length + 1, "product", description));
    }
    return { layout: "unknown", store: findStore(lines), date: findDate(lines.join("\n")), total: null, items_sum: null, sums_match: null, items, unparsed: [] };
  }

  // ------------------------------------------ text read from a picture
  // As receipt.repair_ocr: the price column put right (minus, decimal comma, tax letter), nothing else.
  const OCR_TAIL = /(?<gap>\s+)(?<minus>[-=–—~]{1,2})?\s?(?<whole>[0-9]{1,4})\s?[.,;:]\s?(?<cents>[0-9]{2})(?<rest>[0-9]?\s*[^\s0-9]?\s?\S{0,2})\s*$/;
  function ocrTax(rest) {
    rest = rest.replace(/ /g, "");
    if (!rest) return "";
    if (/[Aa4]/.test(rest)) return "A";
    if (/[Bb8356ß]/.test(rest)) return "B";
    return /^[A-Za-z]$/.test(rest) ? rest.toUpperCase() : "X";
  }
  function repairOcr(text) {
    return String(text).replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n").map((line) => {
      const found = OCR_TAIL.exec(line);
      if (!found || line.trimEnd().endsWith("EUR/kg")) return line;
      const g = found.groups, minus = g.minus ? "-" : "";
      let tax = ocrTax(g.rest);
      if (minus && tax === "X") tax = ""; // a discount line has no tax letter; a deposit return ("-0,75 B") has one
      return `${line.slice(0, found.index)}  ${minus}${g.whole},${g.cents}` + (tax ? ` ${tax}` : "");
    }).join("\n");
  }

  // ------------------------------------------------- description -> phrase
  const PIECE = /(\p{L}+)(\.?)|([0-9]+(?:[.,][0-9]+)?%?)/gu;
  const CAMEL = /(?<=[a-zäöüßéèáàç])(?=[A-ZÄÖÜ])/; // "KerrygoldChed." is two words written without a space

  function pieces(description) {
    const trimmed = String(description).trim();
    const text = trimmed.replace(ARTICLE_NUMBER, "");
    const found = [];
    for (const m of text.matchAll(PIECE)) {
      if (m[3]) { found.push([m[3], "num"]); continue; }
      const parts = m[1].split(CAMEL);
      parts.forEach((part, index) => found.push([part, m[2] && index === parts.length - 1 ? "dot" : ""]));
    }
    const fullWidth = trimmed.length >= CUT_AT || trimmed.length === 15;
    const last = found[found.length - 1];
    if (last && fullWidth && !last[1] && text.trimEnd().endsWith(last[0])) last[1] = "end";
    return found;
  }
  const words = (description) => pieces(description).filter((p) => p[1] !== "num");

  function phrase(description) {
    const out = [], open = [];
    let changed = false;
    for (const [word, cut] of pieces(description)) {
      if (cut === "num") { out.push(word); continue; }
      const key = M.fold(word);
      if (cut === "dot" && Object.prototype.hasOwnProperty.call(ABBREVIATIONS, key)) {
        changed = true;
        if (ABBREVIATIONS[key]) out.push(ABBREVIATIONS[key]);
        continue;
      }
      out.push(word + (cut === "dot" ? "." : ""));
      if (cut && key.length >= MIN_PREFIX) open.push(key);
    }
    return { text: out.join(" "), open, changed };
  }

  // -------------------------------------------------------------- matching
  function recordWords(record) {
    const found = [];
    for (const name of [...record.product_name, record.title, ...record.brand]) {
      for (const word of M.tokens(name)) { found.push(word); found.push(...M.splitCompound(word)); }
    }
    return found;
  }

  function complete(text, open, record) {
    if (!open.length) return text;
    const pool = recordWords(record);
    return text.split(" ").map((word) => {
      const key = M.fold(word.replace(/\.+$/, ""));
      if (open.includes(key)) {
        const longer = pool.find((w) => w.startsWith(key) && w.length > key.length);
        if (longer) return longer;
      }
      return word;
    }).join(" ");
  }

  function brandIn(lineWords, record) {
    for (const brand of record.brand) {
      const parts = M.tokens(brand);
      if (parts.length && parts.every((part) => lineWords.includes(part))) return brand;
    }
    return "";
  }

  function sameShop(a, b) {
    a = M.fold(a); b = M.fold(b);
    return a === b || a.startsWith(b + " ") || b.startsWith(a + " ");
  }

  function lastBestBefore(values) {
    let latest = "";
    for (let value of values) {
      if (value === "alle") return "";
      if (value.includes("..")) {
        value = value.split("..")[1];
        if (!value) return "";
      }
      if (value > latest) latest = value;
    }
    return latest;
  }

  function narrow(record, store, purchaseDate) {
    const reasons = [];
    const sellers = record.sellers || [];
    if (store && sellers.length && !sellers.some((seller) => sameShop(store, seller))) {
      reasons.push(`the notice names other shops only: ${sellers.join(", ")}`);
    }
    if (purchaseDate) {
      const published = String(record.first_published || "") || record.date || "";
      if (/^[0-9]/.test(published) && published.length === 10) {
        const [y, m, d] = published.split("-").map(Number);
        const limit = new Date(Date.UTC(y, m - 1, d + GRACE_DAYS)).toISOString().slice(0, 10);
        if (purchaseDate > limit) reasons.push(`bought more than ${GRACE_DAYS} days after the recall was published (${published})`);
      }
      const latest = lastBestBefore(record.best_before);
      if (latest && purchaseDate.slice(0, latest.length) > latest) {
        reasons.push(`the recalled packs were past their best-before date (${latest}) when you shopped`);
      }
    }
    return reasons;
  }

  function matchLine(description, record, store = "", purchaseDate = "", text = null, minimum = POSSIBLE) {
    const spoken = phrase(description);
    let name = text === null ? spoken.text : text;
    const open = text === null ? spoken.open
      : text.split(" ").filter((w) => w.endsWith(".") && w.length > MIN_PREFIX).map((w) => M.fold(w.replace(/\.+$/, "")));
    name = complete(name, open, record);
    const brand = brandIn(M.tokens(name), record);
    const found = M.matchProduct({ name, brand }, record);
    if (!found || found.score < minimum) return null;
    return {
      notice_id: record.id, title: record.title, recall_name: found.recall_name, score: found.score, reason: found.reason,
      basis: brand ? "name and brand" : "name only", matched_as: name, check: found.identifiers.check,
      less_likely: narrow(record, store, purchaseDate),
    };
  }

  function matchReceipt(parsed, records, store = null, purchaseDate = null) {
    store = store === null ? parsed.store || "" : store;
    purchaseDate = purchaseDate === null ? parsed.date || "" : purchaseDate;
    const found = [];
    for (const it of parsed.items) {
      if (it.kind !== "product" || it.nonfood) continue; // deposits, and non-food articles (the recalls here are food recalls)
      for (const record of records) {
        const hit = matchLine(it.description, record, store, purchaseDate, it.text === undefined ? null : it.text);
        if (hit) found.push({ line_no: it.line_no, description: it.description, ...hit });
      }
    }
    return found.sort((a, b) => (a.less_likely.length > 0) - (b.less_likely.length > 0) || b.score - a.score || a.line_no - b.line_no
      || (a.notice_id < b.notice_id ? -1 : a.notice_id > b.notice_id ? 1 : 0));
  }

  function init(lexicon) {
    RETAILERS = lexicon.retailers || [];
    ABBREVIATIONS = lexicon.receipt_abbrev || {};
    retailerPatterns = null;
  }

  root.RecallReceipt = { init, parse, repairOcr, findStore, findDate, pieces, words, phrase, complete, narrow, sameShop, matchLine, matchReceipt, POSSIBLE };
})(typeof window !== "undefined" ? window : globalThis);
