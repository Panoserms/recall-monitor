# Test fixtures

`SYNTHETIC_receipt_lidl_layout.txt` is **not a real receipt**. It was written by hand in the layout of a
Lidl digital receipt (lidl.de, "Meine Kassenbons") to test the parser: the product names come from the
test records in `tests/test_match.py`, the address, prices, article number and time are made up, and the
tax table is only there so the parser has to skip it. Real receipts are private and never committed;
tests that use them read `~/receipts-lidl/clean/` (or `$RECEIPTS_DIR/clean/`) and are skipped without it.
