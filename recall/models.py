"""The data that moves through the pipeline."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Where a value came from:
#   structured  copied from a dedicated field of the portal, no interpretation
#   rule        found by a linguistic rule inside free text
#   model       proposed by the local language model and found again in the notice text
#   none        nothing found
Source = Literal["structured", "rule", "model", "none"]

FIELDS = (
    "product_name",
    "brand",
    "manufacturer",
    "batch",
    "best_before",
    "reason_category",
    "reason_text",
    "sellers",
    "states",
    "date",
)

REASON_CATEGORIES = ("salmonella", "listeria", "foreign_object", "undeclared_allergen", "other")


class NoticeText(BaseModel):
    """One notice, cut into its labelled sections (see recall/parse.py)."""

    id: str
    title: str
    link: str
    pub_date: str  # ISO 8601, last update according to the feed
    sections: dict[str, str]
    has_page: bool = False
    page_is_current: bool = False  # False: the saved page is older than the notice's last update
    raw_item: str = ""  # the feed <item>, for the picture link
    attachments: list[str] = Field(default_factory=list)  # press release PDFs linked from the page

    def text(self, *names: str) -> str:
        """The given sections joined by line breaks; missing ones are skipped."""
        return "\n".join(self.sections[n] for n in names if self.sections.get(n))


class FieldValue(BaseModel):
    """The value of one field of one notice. Every field is a list; many hold one item."""

    values: list[str] = Field(default_factory=list)
    source: Source = "none"
    rule: str | None = None  # id of the rule that produced the value, e.g. "best_before.dates"
    evidence: str | None = None  # the text the value was read from

    @classmethod
    def empty(cls, rule: str | None = None) -> "FieldValue":
        """Nothing found. With a rule id: the notice itself says the value is unknown."""
        return cls(rule=rule)


class Record(BaseModel):
    """Everything extracted from one notice."""

    id: str
    title: str
    link: str
    pub_date: str
    fields: dict[str, FieldValue]
    extras: dict[str, str | list[str]] = Field(default_factory=dict)  # what_to_do, package, ean, ...

    def values(self, field: str) -> list[str]:
        return self.fields[field].values if field in self.fields else []
