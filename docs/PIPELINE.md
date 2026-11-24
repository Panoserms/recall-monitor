# Pipeline

What each command does. EAN = the number under a barcode.

| Stage | Command | What it does |
|---|---|---|
| 1 fetch | `recall fetch` | Downloads the feed (at most hourly) and each notice page once, one request every 31 s as `robots.txt` asks. Raw responses are saved unchanged in `data/raw/`. A corrected notice gets a new version. |
| 2 extract | `recall extract` | Ten fields per notice: product name, brand, manufacturer, batch, best-before, reason category, reason text, sellers, federal states, date. Every value records its source (`structured` = copied from a labelled portal field, `rule`, `model`), the rule id and the text it was read from. |
| 3 fallback | (part of extract) | Only for open fields. `--no-llm` turns it off; without Ollama the run continues with rules only. |
| 4 normalise | (part of match) | Case and umlauts folded (notices write both *Käse* and *Kaese*), sizes and filler words dropped, compounds split at their head with a small food lexicon (*Rinderhackfleisch* → rinder + hackfleisch), lexicalised compounds kept whole (*Himbeeren* must not match *Heidelbeeren*), brand spellings mapped to one key. |
| 5 match | `recall match` | Score 0–100 from name overlap and brand agreement; an EAN on both sides decides; another brand never alerts. For each match: is your pack affected? (batch, best-before date incl. months and ranges, EAN), or which codes to look for. |
| 6 alert | `recall alert` | One line per match: product, reason, verdict, what to do, link. |
| 7 eval | `recall eval` | Share of fields filled without the model, run times, per-field precision and recall against hand labels. |

## Your product list

`data/my_products.csv` (private, not committed). Copy `data/my_products.example.csv` to start, or use the web app.

```
name,brand,ean,batch,best_before,note
Spinat gehackt,K-Classic,,,31.10.2027,
```

Only `name` is needed. With a best-before date, batch or EAN from the pack, the alert says
*your pack is affected* / *not affected* instead of *check your pack*.
