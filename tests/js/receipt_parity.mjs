// Runs recall/site/static/match.js and receipt.js on the cases written by tests/test_receipt_parity.py
// (or scripts/receipt_eval.py --engine js) and prints their answers.
import { readFileSync } from "node:fs";
import { runInThisContext } from "node:vm";

const [matchScript, receiptScript, casesPath] = process.argv.slice(2);
runInThisContext(readFileSync(matchScript, "utf8"));
runInThisContext(readFileSync(receiptScript, "utf8"));
const M = globalThis.RecallMatch, R = globalThis.RecallReceipt;
const cases = JSON.parse(readFileSync(casesPath, "utf8"));
M.init(cases.lexicon);
R.init(cases.lexicon);
const out = {
  parsed: (cases.texts || []).map((t) => R.parse(t)),
  pieces: (cases.descriptions || []).map((d) => R.pieces(d)),
  phrases: (cases.descriptions || []).map((d) => R.phrase(d)),
  stores: (cases.store_lines || []).map((lines) => R.findStore(lines)),
  dates: (cases.date_texts || []).map((t) => R.findDate(t)),
  repaired: (cases.ocr_texts || []).map((t) => R.repairOcr(t)),
  narrowed: (cases.narrow || []).map(([r, store, date]) => R.narrow(cases.records[r], store, date)),
  lines: (cases.lines || []).map(([description, r, store, date, text, minimum]) =>
    R.matchLine(description, cases.records[r], store, date, text, minimum === null || minimum === undefined ? R.POSSIBLE : minimum)),
  receipts: (cases.receipts || []).map(([t, store, date]) => R.matchReceipt(R.parse(cases.texts[t]), cases.records, store, date)),
};
process.stdout.write(JSON.stringify(out));
