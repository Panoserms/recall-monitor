"""Paths and the facts about the portal that the code relies on."""
from __future__ import annotations

import os
from pathlib import Path

# The project folder. Set RECALL_HOME to keep data somewhere else.
ROOT = Path(os.environ.get("RECALL_HOME") or Path(__file__).resolve().parent.parent)
DATA = ROOT / "data"
RAW = DATA / "raw"
DB_PATH = DATA / "recall.db"
MY_PRODUCTS = DATA / "my_products.csv"
MY_PRODUCTS_EXAMPLE = DATA / "my_products.example.csv"
BRAND_ALIASES = DATA / "brand_aliases.csv"
GOLD = DATA / "gold.csv"
GOLD_TEMPLATE = DATA / "gold_template.csv"
MATCH_GOLD = DATA / "match_gold.csv"
SITE_SETTINGS = ROOT / "site.json"
SITE_OUT = ROOT / "public"

# Official RSS feed, food notices only, all federal states (checked 2026-11-11).
FEED_URL = (
    "https://www.lebensmittelwarnung.de/___LMW-Redaktion/RSSNewsfeed/Functions/RssFeeds/"
    "rssnewsfeed_Alle_DE.xml?nn=314268&type=lebensmittel"
)

# robots.txt of www.lebensmittelwarnung.de, read 2026-11-11:
#   Disallow: /SiteGlobals/   Disallow: /DE/Service/   Disallow: /EN/Service/
#   Allow: /SiteGlobals/Modules/ /SiteGlobals/StyleBundles/ /SiteGlobals/Frontend/
#   Crawl-delay: 30
ALLOWED_HOST = "www.lebensmittelwarnung.de"
DISALLOWED_PREFIXES = ("/SiteGlobals/", "/DE/Service/", "/EN/Service/")
MIN_DELAY_S = 31.0  # one second more than the crawl delay the site asks for

# The feed says <ttl>60</ttl> and "Cache-Control: max-age=3601": ask at most hourly.
FEED_TTL_S = 3600

USER_AGENT = os.environ.get("RECALL_USER_AGENT") or "recall-monitor/1.0 (personal food recall checker; honours Crawl-delay 30)"
REQUEST_TIMEOUT_S = 60

# Local model for the fallback stage.
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("RECALL_MODEL", "gemma4:e2b-it-qat")
