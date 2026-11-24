"""Read the official RSS feed: one <item> per notice."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

ITEM = re.compile(r"<item>.*?</item>", re.S)
TITLE = re.compile(r"<title>(.*?)</title>", re.S)
LINK = re.compile(r"<link>(.*?)</link>", re.S)
PUB_DATE = re.compile(r"<pubDate>(.*?)</pubDate>", re.S)


@dataclass(frozen=True)
class FeedItem:
    id: str
    link: str
    title: str
    pub_date: datetime  # last update of the notice, with its time zone
    raw: str  # the <item> exactly as the server sent it


def notice_id(link: str) -> str:
    """A short, file-safe id for a notice.

    Real link: .../Meldungen/2026/11_November/261109_09_NI_Corned_Beef/261109_09_NI_Corned_Beef.html
    -> "261109_09_NI_Corned_Beef" (the folder: date, running number, reporting state, product).
    """
    m = re.search(r"/Meldungen/(?:[^/]+/)+([^/]+)/[^/]+\.html$", link)
    if m:
        return re.sub(r"[^A-Za-z0-9_-]", "_", m.group(1))
    return "n_" + hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def version_of(pub_date: datetime) -> str:
    """The version of a notice is the time of its last update, e.g. "20261110T1435"."""
    return pub_date.strftime("%Y%m%dT%H%M")


def parse_feed(data: bytes) -> list[FeedItem]:
    text = data.decode("utf-8")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("feed declares a DOCTYPE or entities; refusing to read it")
    items = []
    for raw in ITEM.findall(text):
        link = html.unescape(LINK.search(raw).group(1)).strip()
        items.append(
            FeedItem(
                id=notice_id(link),
                link=link,
                title=html.unescape(TITLE.search(raw).group(1)).strip(),
                pub_date=parsedate_to_datetime(PUB_DATE.search(raw).group(1).strip()),
                raw=raw,
            )
        )
    return items
