"""Split a notice into its labelled sections.

The portal already labels most of a notice ("Grund der Meldung:", "Haltbarkeit:", ...).
This module only cuts along those labels; it does not interpret the text.
Interpretation is the job of recall/rules/.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

# Portal label -> our section name. Same labels in the feed and on the page.
LABELS = {
    "Produktbezeichnung/ -beschreibung": "product",
    "Chargennummer / Los-Kennzeichnung": "batch",
    "Haltbarkeit": "best_before",
    "Verpackungseinheit": "package",
    "Hersteller / Inverkehrbringer": "manufacturer",
    "Grund der Meldung": "reason_official",
    "Weitere Informationen": "more_info",
    "Mögliche Folgen": "consequences",
    "Betroffene Bundesländer nach derzeitigem Stand": "states",
    "Empfehlung": "recommendation",
    "Vertrieb über": "sold_via",
    "Weitere Kennzeichnung": "marking",
    "Produktionsdatum": "production_date",
    "Weitere Informationen zur Meldung": "notice_info",
    "Kontakt": "contact",
    "Bildquelle": "image_source",
    "Meldungserstellung durch": "reported_by",
    "Datum der Erstveröffentlichung": "first_published",
    "Letzte Aktualisierung": "last_updated",
    "Aktualisierungshinweise": "update_notes",
}


def _section_name(label: str) -> str:
    label = re.sub(r"\s+", " ", label).strip().rstrip(":").strip()
    return LABELS.get(label, f"other:{label}")


def _tidy(text: str) -> str:
    """One trimmed line per line of the source; empty lines dropped."""
    lines = (re.sub(r"[ \t\r\f\v\xa0]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def _add(sections: dict[str, str], name: str, value: str) -> None:
    if not value:
        return
    sections[name] = f"{sections[name]}\n{value}" if name in sections else value


# ---------------------------------------------------------------------- feed

_DESCRIPTION = re.compile(r"<description><!\[CDATA\[(.*?)\]\]></description>", re.S)
# <b>Label:</b> value ... up to the next <br/><b> or the end of the description
_FEED_FIELD = re.compile(r"<b>(.*?)</b>(.*?)(?=<br/>\s*<b>|\Z)", re.S)


def feed_sections(raw_item: str) -> dict[str, str]:
    """Sections of one feed <item>.

    Real example: "<b>Grund der Meldung:</b>   Fremdkörper<br/><b>Haltbarkeit:</b> Mindesthaltbarkeitsdatum: 01.03.2028, ..."
    """
    found = _DESCRIPTION.search(raw_item)
    if not found:
        return {}
    sections: dict[str, str] = {}
    for label, value in _FEED_FIELD.findall(found.group(1)):
        value = re.sub(r"<br\s*/?>", "\n", value)
        value = html.unescape(re.sub(r"<[^>]+>", " ", value))
        _add(sections, _section_name(html.unescape(label)), _tidy(value))
    return sections


# ---------------------------------------------------------------------- page

class _DescriptionLists(HTMLParser):
    """Collects every <dt>label</dt><dd>value</dd> pair and the links to attached files.

    Real example: <dt class="lmw-description-list__term">Weitere Informationen: </dt>
                  <dd class="lmw-description-list__description"><p>Der Rückruf erfolgt vorsorglich, ...</p></dd>
    """

    _BREAKS = {"br", "p", "li", "div", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pairs: list[tuple[str, str]] = []
        self.files: list[str] = []
        self._mode: str | None = None
        self._buffer: list[str] = []
        self._term = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("dt", "dd"):
            self._mode, self._buffer = tag, []
        elif self._mode == "dd" and tag in self._BREAKS:
            self._buffer.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if "__blob=publicationFile" in href and href not in self.files:
                self.files.append(href)

    def handle_endtag(self, tag):
        if tag == "dt" and self._mode == "dt":
            self._term, self._mode = "".join(self._buffer), None
        elif tag == "dd" and self._mode == "dd":
            self.pairs.append((self._term, "".join(self._buffer)))
            self._mode = None
        elif self._mode == "dd" and tag in self._BREAKS:
            self._buffer.append("\n")

    def handle_data(self, data):
        if self._mode:
            self._buffer.append(data)


def _parsed(page: bytes) -> _DescriptionLists:
    parser = _DescriptionLists()
    parser.feed(page.decode("utf-8", errors="replace"))
    parser.close()
    return parser


def page_sections(page: bytes) -> dict[str, str]:
    """Sections of one notice page. The page has everything the feed has, plus the reason
    text ("Weitere Informationen"), the advice ("Empfehlung") and the publication dates."""
    sections: dict[str, str] = {}
    for label, value in _parsed(page).pairs:
        _add(sections, _section_name(label), _tidy(value))
    return sections


def page_attachments(page: bytes) -> list[str]:
    """Links to files attached to the notice, usually the company's press release (PDF)."""
    return _parsed(page).files


def _label(label: str) -> str:
    return re.sub(r"\s+", " ", label).strip().rstrip(":").strip()


def page_pairs(page: bytes) -> list[tuple[str, str]]:
    """The notice as the portal shows it: (portal label, text) in page order. Line breaks and spaces are
    tidied, the words are not changed. The public site shows this in full next to the extracted fields,
    because the portal's terms ask for notices to be republished complete and unchanged."""
    return [(_label(label), _tidy(value)) for label, value in _parsed(page).pairs if _tidy(value)]


def feed_pairs(raw_item: str) -> list[tuple[str, str]]:
    """The same for a feed <item>, for notices without a saved page."""
    found = _DESCRIPTION.search(raw_item)
    if not found:
        return []
    pairs = []
    for label, value in _FEED_FIELD.findall(found.group(1)):
        value = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<br\s*/?>", "\n", value)))
        if _tidy(value):
            pairs.append((_label(html.unescape(label)), _tidy(value)))
    return pairs


def merge_sections(feed: dict[str, str], page: dict[str, str] | None) -> dict[str, str]:
    """The page is the fuller source; the feed fills in what the page does not show."""
    return {**feed, **(page or {})}
