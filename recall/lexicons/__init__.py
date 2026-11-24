"""Word lists used by the rules. Plain text files, one entry per line, tab-separated columns."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_HERE = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load(name: str) -> tuple[tuple[str, ...], ...]:
    """Rows of a lexicon file. Lines starting with # and empty lines are skipped."""
    rows = []
    for line in (_HERE / name).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            rows.append(tuple(cell.strip() for cell in line.split("\t")))
    return tuple(rows)
