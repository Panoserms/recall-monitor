"""Stage 6: alerts are read back from the database as one line per match."""

from test_match import SPINACH, mine

from recall import alert, extract, match


def _store(conn, record):
    """Put one notice and its record into the database (other notices stay active)."""
    conn.execute(
        "INSERT OR REPLACE INTO notices (id, link, title, pub_date, feed_item, first_seen, last_seen, active)"
        " VALUES (?, ?, ?, ?, '<item></item>', '2026-11-12', '2026-11-12', 1)",
        (record.id, record.link, record.title, record.pub_date),
    )
    conn.execute("BEGIN")
    extract.save_record(conn, record)
    conn.execute("COMMIT")


def test_alert_line_has_product_reason_verdict_advice_and_link(conn):
    _store(conn, SPINACH)
    match.save_matches(conn, match.find_matches([mine("Spinat gehackt", "K-Classic", best_before="31.10.2027")], [SPINACH]))
    [item] = alert.load_alerts(conn)
    line = item.line()
    assert line.startswith("[MATCH ")
    assert "Spinat gehackt (K-Classic)" in line
    assert "Fremdkörper" in line
    assert "YOUR PACK IS AFFECTED" in line and "MHD 10/2027" in line
    assert "Kaufland Filialen zurückgegeben" in line
    assert line.endswith(SPINACH.link)


def test_notices_removed_from_the_portal_give_no_alert(conn):
    _store(conn, SPINACH)
    match.save_matches(conn, match.find_matches([mine("Spinat gehackt", "K-Classic")], [SPINACH]))
    conn.execute("UPDATE notices SET active = 0")
    assert alert.load_alerts(conn) == []
