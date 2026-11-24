"""Field: manufacturer - the companies named as maker, distributor or importer."""
from __future__ import annotations

from ..companies import company_names
from ..models import FieldValue, NoticeText
from ..textutils import one_line


def extract(notice: NoticeText) -> FieldValue:
    text = notice.sections.get("manufacturer", "").strip()
    names = company_names(text)
    if not names:
        return FieldValue.empty()
    if names == [text]:
        # Rule manufacturer.field: the field holds nothing but the name.   "Tema Fine Foods"
        return FieldValue(values=names, source="structured", rule="manufacturer.field", evidence=text)
    # Rule manufacturer.name_before_address: the name is the first line of each address block;
    # a role label or the line after a postcode starts the next company.
    #   "Hersteller: Recker Convenience GmbH, Diepholzer Straße 81, 49453 Wetschen, 49453 Rehden
    #    Inverkehrbringer: REWE Markt GmbH, Domstraße 20, 50668 Köln"
    return FieldValue(values=names, source="rule", rule="manufacturer.name_before_address", evidence=one_line(text))
