"""Stage 4: normalising product names and brands for matching. Inputs are real product names from notices."""
import pytest

from recall import normalise


def test_fold_lowercases_and_spells_umlauts_out():
    # the portal writes both: "Schnittkaese aus Rohmilch" and "Weichkäse"
    assert normalise.fold("Schnittkäse aus Rohmilch") == normalise.fold("Schnittkaese aus Rohmilch")
    assert normalise.fold("Gemüsemais, Süß") == "gemuesemais, suess"


@pytest.mark.parametrize(
    "name, want",
    [
        ("K-Classic Spinat gehackt, erntefrisch tiefgefroren 1000 Gramm", ["k", "classic", "spinat", "gehackt", "erntefrisch", "tiefgefroren"]),
        ("Deutsches Corned Beef, 160 Gramm", ["deutsches", "corned", "beef"]),
        ("Royal Honey-The Ultimate Power Source, 12x20 Gramm", ["royal", "honey", "the", "ultimate", "power", "source"]),
        ("Bio Wildreis Basmati Reis Mix, 0,6 und 3 Kilogramm", ["bio", "wildreis", "basmati", "reis", "mix"]),
        ("Mini Brie mit Nuss", ["mini", "brie", "nuss"]),
    ],
)
def test_tokens_drop_sizes_punctuation_and_filler_words(name, want):
    assert normalise.tokens(name) == want


@pytest.mark.parametrize(
    "word, want",
    [
        ("rinderhackfleisch", ["rinder", "hackfleisch", "hack", "fleisch"]),
        ("weichkaese", ["weich", "kaese"]),
        ("pinienkerne", ["pinien", "kerne"]),
        ("fruchtaufstrich", ["frucht", "aufstrich"]),
        ("himbeeren", []),  # lexicalised: "Himbeeren" must not match "Heidelbeeren" by the head "beeren"
        ("spinat", []),  # not a compound
        ("kaese", []),  # a word of the lexicon itself is not split
    ],
)
def test_compounds_are_split_at_their_head(word, want):
    assert normalise.split_compound(word) == want


def test_brand_variants_map_to_one_name():
    assert normalise.brand_key("Gut&Günstig") == normalise.brand_key("GUT & GÜNSTIG") == normalise.brand_key("gut und günstig")
    assert normalise.brand_key("K Classic") == normalise.brand_key("K-Classic")


def test_unknown_brands_are_only_folded():
    assert normalise.brand_key("Zörbiger") == "zoerbiger"
