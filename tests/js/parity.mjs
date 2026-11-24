// Runs recall/site/static/match.js on the cases written by tests/test_site_parity.py and prints its answers.
import { readFileSync } from "node:fs";
import { runInThisContext } from "node:vm";

const [script, casesPath] = process.argv.slice(2);
runInThisContext(readFileSync(script, "utf8"));
const M = globalThis.RecallMatch;
const cases = JSON.parse(readFileSync(casesPath, "utf8"));
M.init(cases.lexicon);
const out = {
  tokens: cases.texts.map((t) => M.tokens(t)),
  splits: cases.words.map((w) => M.splitCompound(w)),
  brand_keys: cases.brands.map((b) => M.brandKey(b)),
  dates: cases.date_inputs.map((d) => M.findDates(d)),
  ratios: cases.ratio_pairs.map(([a, b]) => M.ratio(a, b)),
  matches: cases.pairs.map(([p, r]) => {
    const m = M.matchProduct(cases.products[p], cases.records[r]);
    return m && { score: m.score, level: m.level, reason: m.reason, recall_name: m.recall_name, identifiers: m.identifiers };
  }),
};
process.stdout.write(JSON.stringify(out));
