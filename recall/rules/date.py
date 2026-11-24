"""Field: date - the day the notice was first published (ISO date)."""
from __future__ import annotations

import re

from ..models import FieldValue, NoticeText
from ..textutils import find_dates

# Rule date.from_link: the link of a notice starts with the day it was created.
#   ".../261109_09_NI_Corned_Beef/..." -> 2026-11-09      ".../20260701_01_ST_Thymiangewuerzmischung/..." -> 2026-07-01
# On 160 pages checked on 2026-11-11 this day equals the first publication in 137 cases
# and is one to five days earlier in the rest, so it is only used when there is no page.
_LINK_DATE = re.compile(r"^(?:20)?(\d{2})(\d{2})(\d{2})_")


def extract(notice: NoticeText) -> FieldValue:
    # Rule date.first_published: page field "Datum der Erstveröffentlichung: 06.11.2026"
    published = notice.sections.get("first_published", "")
    dates = find_dates(published)
    if dates:
        return FieldValue(values=[dates[0].iso], source="structured", rule="date.first_published", evidence=published)
    in_link = _LINK_DATE.match(notice.id)
    if in_link:
        year, month, day = (int(g) for g in in_link.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            return FieldValue(
                values=[f"20{year:02d}-{month:02d}-{day:02d}"], source="rule", rule="date.from_link", evidence=notice.id
            )
    # Rule date.feed_pubdate: the feed's <pubDate>. It is the day of the last update, the best the feed has.
    return FieldValue(values=[notice.pub_date[:10]], source="structured", rule="date.feed_pubdate", evidence=notice.pub_date)
