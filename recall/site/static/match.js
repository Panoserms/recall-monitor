// Matching in the browser: a line-by-line port of recall/normalise.py, recall/match.py and
// textutils.find_dates, so that a visitor's product list never leaves their browser.
// tests/test_site_parity.py runs the same cases through Python and this file and requires equal results.
(function (root) {
  "use strict";

  let FOOD = new Set();
  let ALIASES = {};
  let FILLER = new Set();
  const MATCH = 80, POSSIBLE = 65;

  // ------------------------------------------------------------ normalise
  const FOLD = { "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "é": "e", "è": "e", "á": "a", "à": "a", "ç": "c", "ñ": "n" };
  const fold = (text) => text.toLowerCase().replace(/[äöüßéèáàçñ]/g, (c) => FOLD[c]);

  // Pack sizes, as textutils.SIZE: "160 Gramm", "12x800 Gramm", "1,5 l", "50 Gramm/60 Kapseln", "20 Aufgussbeutel á 2 Gramm"
  const UNIT = "(?:Kilogramm|Milligramm|Gramm|Milliliter|Zentiliter|Liter|Unzen|Stück|Stueck|Stk\\.?|Packungen|Portionen|" +
    "Aufgussbeutel|Teebeutel|Beutel|Kapseln|Tabletten|packets|oz|kg|mg|gr|g|ml|cl|l)";
  const ONE_SIZE = `(?:\\d+\\s*[x×]\\s*)?\\d+(?:[.,]\\d+)?\\s*${UNIT}(?![\\p{L}\\p{N}_-])\\.?`;
  const SIZE = new RegExp(`(?<![\\p{L}\\p{N}_.,/#-])(?:${ONE_SIZE})(?:\\s*(?:/|á|à|je)\\s*${ONE_SIZE})*`, "giu");

  function tokens(text) {
    const words = fold(String(text).replace(SIZE, " ")).match(/[a-z0-9]+/g) || [];
    return words.filter((w) => !FILLER.has(w) && !/^\d+$/.test(w));
  }

  const splitCache = new Map();
  function splitOnce(word) {
    for (let i = 3; i < word.length - 2; i++) if (FOOD.has(word.slice(i))) return [word.slice(0, i), word.slice(i)];
    return null;
  }
  function splitCompound(word) {
    if (splitCache.has(word)) return splitCache.get(word);
    let parts = [];
    const split = splitOnce(word);
    if (split && !(FOOD.has(word) && !FOOD.has(split[0]))) parts = [split[0], split[1], ...splitCompound(split[1])];
    splitCache.set(word, parts);
    return parts;
  }

  const key = (text) => fold(String(text)).replace(/&/g, "und").replace(/[^a-z0-9!]/g, "");
  const brandKey = (brand) => { const k = key(brand); return Object.prototype.hasOwnProperty.call(ALIASES, k) ? ALIASES[k] : k; };

  // ------------------------------------------------------------------ dates
  const MONTHS = { januar: 1, jan: 1, februar: 2, feb: 2, "märz": 3, maerz: 3, mrz: 3, april: 4, apr: 4, mai: 5, juni: 6, jun: 6,
    juli: 7, jul: 7, august: 8, aug: 8, september: 9, sept: 9, sep: 9, oktober: 10, okt: 10, november: 11, nov: 11, dezember: 12, dez: 12 };
  const MONTH = Object.keys(MONTHS).sort((a, b) => b.length - a.length).join("|");
  const DATE = new RegExp([
    "(?<ymd>(?<!\\d)(?<y1>20\\d{2})[/.-](?<m1>\\d{1,2})[/.-](?<d1>\\d{1,2})(?!\\d))",
    "(?<dmy>(?<![\\d.])(?<d2>\\d{1,2})(?<sep>[./-])(?<m2>\\d{1,2})\\k<sep>(?<y2>\\d{4}|\\d{2})(?!\\d))",
    `(?<dname>(?<!\\d)(?<d3>\\d{1,2})\\.\\s*(?<m3>${MONTH})\\.?\\s+(?<y3>20\\d{2}))`,
    "(?<my>(?<![\\d./-])(?<m4>\\d{1,2})[./-](?<y4>20\\d{2})(?!\\d))",
    `(?<mname>(?<![A-Za-zÄÖÜäöüß])(?<m5>${MONTH})\\.?\\s*/?\\s*(?<y5>20\\d{2}))`,
  ].join("|"), "giu");
  const pad = (n) => String(n).padStart(2, "0");
  function iso(year, month, day) {
    if (year < 100) year += 2000;
    if (!(year >= 2000 && year <= 2099 && month >= 1 && month <= 12)) return null;
    if (day === null) return `${year}-${pad(month)}`;
    if (!(day >= 1 && day <= 31)) return null;
    return `${year}-${pad(month)}-${pad(day)}`;
  }
  function findDates(text) {
    const found = [];
    for (const m of String(text).matchAll(DATE)) {
      const g = m.groups;
      let value = null;
      if (g.ymd) value = iso(+g.y1, +g.m1, +g.d1);
      else if (g.dmy) value = iso(+g.y2, +g.m2, +g.d2);
      else if (g.dname) value = iso(+g.y3, MONTHS[g.m3.toLowerCase()], +g.d3);
      else if (g.my) value = iso(+g.y4, +g.m4, null);
      else if (g.mname) value = iso(+g.y5, MONTHS[g.m5.toLowerCase()], null);
      if (value) found.push(value);
    }
    return found;
  }

  // ----------------------------------------------------------------- names
  function lcs(a, b) {
    const row = new Array(b.length + 1).fill(0);
    for (let i = 1; i <= a.length; i++) {
      let prev = 0;
      for (let j = 1; j <= b.length; j++) {
        const keep = row[j];
        row[j] = a[i - 1] === b[j - 1] ? prev + 1 : Math.max(row[j], row[j - 1]);
        prev = keep;
      }
    }
    return row[b.length];
  }
  // rapidfuzz fuzz.ratio: normalised Indel similarity
  const ratio = (a, b) => (a.length + b.length ? (200 * lcs(a, b)) / (a.length + b.length) : 100);

  function same(a, b) {
    if (a === b) return true;
    const [short, long] = a.length <= b.length ? [a, b] : [b, a];
    if (short.length >= 4 && long.startsWith(short) && long.length - short.length <= 3) return true;
    return Math.min(a.length, b.length) >= 5 && ratio(a, b) >= 88;
  }

  function found(word, others) {
    const pool = new Set(others);
    for (const other of others) for (const part of splitCompound(other)) pool.add(part);
    for (const other of pool) if (same(word, other)) return 1;
    const parts = splitCompound(word);
    if (parts.length) {
      let head = false, modifier = false;
      for (const other of pool) { if (same(parts[1], other)) head = true; if (same(parts[0], other)) modifier = true; }
      if (head) return modifier ? 1 : 0.5;
    }
    return 0;
  }

  const mean = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;
  function nameScore(mine, theirs) {
    if (!mine.length || !theirs.length) return [0, []];
    const hits = mine.map((w) => found(w, theirs));
    const back = mean(theirs.map((w) => found(w, mine)));
    return [100 * (0.75 * mean(hits) + 0.25 * back), mine.filter((w, i) => hits[i])];
  }
  const without = (words, remove) => words.filter((w) => !remove.has(w));
  const contains = (words, part) => part.length > 0 &&
    words.some((_, i) => i + part.length <= words.length && part.every((p, j) => words[i + j] === p));

  // ---------------------------------------------------------------- brands
  function brandStatus(product, record) {
    if (!product.brand.trim()) return ["unknown", ""];
    const k = brandKey(product.brand);
    for (const brand of record.brand) {
      const theirs = brandKey(brand);
      if (k === theirs || (k.length >= 4 && (theirs.includes(k) || k.includes(theirs)))) return ["same", brand];
    }
    const mine = tokens(product.brand);
    for (const text of [record.title, ...record.product_name]) if (contains(tokens(text), mine)) return ["same", product.brand];
    for (const company of record.manufacturer) if (k.length >= 4 && brandKey(company).includes(k)) return ["same", company];
    if (record.brand.length) return ["different", record.brand.join(", ")];
    return ["unknown", ""];
  }

  // ----------------------------------------------------------------- match
  const levelOf = (score) => (score >= MATCH ? "match" : score >= POSSIBLE ? "possible" : "none");
  // Python formats and rounds half to even ("{:.0f}", round(x, 1))
  function roundEven(x, digits) {
    const f = 10 ** digits, y = x * f, r = Math.round(y);
    return (Math.abs(y % 1) === 0.5 ? (r % 2 === 0 ? r : r - 1) : r) / f;
  }

  function normProduct(p) {
    const s = (v) => String(v ?? "");
    return { name: s(p.name), brand: s(p.brand), ean: s(p.ean), batch: s(p.batch), best_before: s(p.best_before) };
  }

  function matchProduct(productIn, record) {
    const product = normProduct(productIn);
    const result = (score, recallName, reason) => (levelOf(score) === "none" ? null : {
      notice_id: record.id, title: record.title, link: record.link, recall_name: recallName,
      score: roundEven(score, 1), level: levelOf(score), reason, identifiers: checkIdentifiers(product, record),
    });
    const myEan = product.ean.replace(/ /g, "");
    if (myEan && record.ean.includes(myEan)) {
      return result(100, record.product_name[0] || record.title, `EAN ${myEan} is listed in the notice`);
    }
    const remove = new Set([...tokens(product.brand), ...record.brand.flatMap((b) => tokens(b))]);
    const mine = without(tokens(product.name), remove);
    let best = [0, [], ""];
    for (const name of [...record.product_name, record.title]) {
      const [score, shared] = nameScore(mine, without(tokens(name), remove));
      if (score > best[0]) best = [score, shared, name];
    }
    const [score, shared, recallName] = best;
    if (!score) return null;
    const [status, decidedBy] = brandStatus(product, record);
    const reason = `name ${roundEven(score, 0)} (shared: ${shared.join(", ")})`;
    if (status === "same") return result(score * 0.6 + 40, recallName, `${reason}; same brand: ${decidedBy}`);
    if (status === "different") return null;
    const note = product.brand.trim() ? `brand ${product.brand} not named in the notice` : "no brand given";
    return result(score * 0.85, recallName, `${reason}; ${note}`);
  }

  // ----------------------------------------------------------- identifiers
  const normCode = (code) => [...code.toUpperCase()].filter((ch) => /[\p{L}\p{N}]/u.test(ch)).join("");
  function batchListed(mine, recalled) {
    const m = normCode(mine);
    for (const code of recalled) {
      if (code === "alle") return true;
      if (code.includes(" bis ")) {
        const at = code.indexOf(" bis ");
        const low = normCode(code.slice(0, at)), high = normCode(code.slice(at + 5));
        if (low.length === high.length && high.length === m.length && low <= m && m <= high) return true;
        continue;
      }
      const c = normCode(code);
      if (m === c || (Math.min(m.length, c.length) >= 4 && (c.includes(m) || m.includes(c)))) return true;
    }
    return false;
  }
  function dateListed(mine, recalled) {
    for (const value of recalled) {
      if (value === "alle") return true;
      if (value.includes("..")) {
        const [low, high] = value.split("..");
        const size = Math.min(mine.length, (low || mine).length, (high || mine).length);
        if ((!low || low.slice(0, size) <= mine.slice(0, size)) && (!high || mine.slice(0, size) <= high.slice(0, size))) return true;
      } else if (mine.startsWith(value) || value.startsWith(mine)) return true;
    }
    return false;
  }
  function showDate(value) {
    if (value === "alle") return "alle";
    if (value.includes("..")) {
      const [low, high] = value.split("..");
      return low ? `${showDate(low)} – ${showDate(high)}` : `bis ${showDate(high)}`;
    }
    const p = value.split("-");
    return p.length === 2 ? `${p[1]}/${p[0]}` : `${p[2]}.${p[1]}.${p[0]}`;
  }
  function checkIdentifiers(productIn, record) {
    const product = normProduct(productIn);
    const checks = {};
    if (product.ean.trim() && record.ean.length) checks.ean = record.ean.includes(product.ean.replace(/ /g, ""));
    if (product.batch.trim() && record.batch.length) checks.batch = batchListed(product.batch, record.batch);
    const mineDates = product.best_before.trim() ? findDates(product.best_before) : [];
    if (mineDates.length && record.best_before.length) checks.best_before = dateListed(mineDates[0], record.best_before);
    const values = Object.values(checks);
    const verdict = values.length && values.every(Boolean) ? "affected" : values.length && !values.some(Boolean) ? "not_affected" : "check";
    const lookFor = [];
    if (record.batch.length) lookFor.push("Charge " + record.batch.join(", "));
    if (record.best_before.length) lookFor.push("MHD " + record.best_before.map(showDate).join(", "));
    if (record.ean.length) lookFor.push("EAN " + record.ean.join(", "));
    return { verdict, checks, check: lookFor.length ? lookFor.join(" · ") : "the notice names no batch, date or EAN: every pack counts" };
  }

  function findMatches(products, records) {
    const out = [];
    products.forEach((p, i) => records.forEach((r) => {
      const m = matchProduct(p, r);
      if (m) out.push({ ...m, product: { ...normProduct(p), row: i + 1 } });
    }));
    return out.sort((a, b) => b.score - a.score || a.product.row - b.product.row || (a.notice_id < b.notice_id ? -1 : a.notice_id > b.notice_id ? 1 : 0));
  }

  function init(lexicon) {
    FOOD = new Set(lexicon.food_words);
    ALIASES = lexicon.brand_aliases;
    FILLER = new Set(lexicon.filler);
    splitCache.clear();
  }

  root.RecallMatch = { init, fold, tokens, splitCompound, brandKey, findDates, ratio, matchProduct, checkIdentifiers, findMatches, showDate, levelOf };
})(typeof window !== "undefined" ? window : globalThis);
