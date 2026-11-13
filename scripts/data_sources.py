"""Data-source validation and feed catalogs; importing this module reads no files."""

from typing import Dict, List
from runtime.environment import configured_value


def env_str(name: str, default: str = "") -> str:
    value = configured_value(name, default)
    if value is None:
        return default
    text = str(value).strip().strip('"').strip("'")
    return text or default


def source_value(name: str) -> str:
    """An absent source has no hidden endpoint/proxy fallback."""
    return configured_value(name).strip()


def resolve_source_references(value):
    """Resolve catalog ${NAME} leaves, never expose the complete environment."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        name = value[2:-1]
        if not name.replace("_", "").isalnum() or name != name.upper():
            raise ValueError("Invalid source configuration reference")
        return source_value(name)
    if isinstance(value, list):
        return [resolve_source_references(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve_source_references(item) for key, item in value.items()}
    return value


def rss_feeds() -> List[Dict[str, str]]:
    return [
        {
            "source": "BBC World",
            "url": source_value('POLYDATA_RSS_BBC_WORLD_URL'),
            "category": "World",
        },
        {
            "source": "BBC Politics",
            "url": source_value('POLYDATA_RSS_BBC_POLITICS_URL'),
            "category": "Politics",
        },
        {
            "source": "Guardian World",
            "url": source_value('POLYDATA_RSS_GUARDIAN_WORLD_URL'),
            "category": "World",
        },
        {
            "source": "NPR News",
            "url": source_value('POLYDATA_RSS_NPR_NEWS_URL'),
            "category": "US",
        },
        {
            "source": "PBS NewsHour",
            "url": source_value('POLYDATA_RSS_PBS_NEWSHOUR_URL'),
            "category": "US",
        },
        {
            "source": "ABC News",
            "url": source_value('POLYDATA_RSS_ABC_NEWS_URL'),
            "category": "US",
        },
        {
            "source": "CBS News",
            "url": source_value('POLYDATA_RSS_CBS_NEWS_URL'),
            "category": "US",
        },
        {
            "source": "NBC News",
            "url": source_value('POLYDATA_RSS_NBC_NEWS_URL'),
            "category": "US",
        },
        {
            "source": "Axios",
            "url": source_value('POLYDATA_RSS_AXIOS_URL'),
            "category": "US",
        },
        {
            "source": "AP News",
            "url": source_value('POLYDATA_RSS_AP_NEWS_URL'),
            "category": "World",
        },
        {
            "source": "CNN World",
            "url": source_value('POLYDATA_RSS_CNN_WORLD_URL'),
            "category": "World",
        },
        {
            "source": "France 24",
            "url": source_value('POLYDATA_RSS_FRANCE24_URL'),
            "category": "World",
        },
        {
            "source": "Euronews",
            "url": source_value('POLYDATA_RSS_EURONEWS_URL'),
            "category": "World",
        },
        {
            "source": "DW News",
            "url": source_value('POLYDATA_RSS_DW_NEWS_URL'),
            "category": "World",
        },
        {
            "source": "Reuters World",
            "url": source_value('POLYDATA_RSS_REUTERS_WORLD_URL'),
            "category": "World",
        },
        {
            "source": "Reuters Business",
            "url": source_value('POLYDATA_RSS_REUTERS_BUSINESS_URL'),
            "category": "Finance",
        },
        {
            "source": "Politico",
            "url": source_value('POLYDATA_RSS_POLITICO_URL'),
            "category": "Politics",
        },
        {
            "source": "The Hill",
            "url": source_value('POLYDATA_RSS_THE_HILL_URL'),
            "category": "Politics",
        },
        {
            "source": "White House",
            "url": source_value('POLYDATA_RSS_WHITE_HOUSE_URL'),
            "category": "Government",
        },
        {
            "source": "Federal Reserve",
            "url": source_value('POLYDATA_RSS_FEDERAL_RESERVE_URL'),
            "category": "Government",
        },
        {
            "source": "SEC",
            "url": source_value('POLYDATA_RSS_SEC_URL'),
            "category": "Government",
        },
        {
            "source": "UN News",
            "url": source_value('POLYDATA_RSS_UN_NEWS_URL'),
            "category": "Government",
        },
        {
            "source": "CISA",
            "url": source_value('POLYDATA_RSS_CISA_URL'),
            "category": "Government",
        },
        {
            "source": "Al Jazeera",
            "url": source_value('POLYDATA_RSS_AL_JAZEERA_URL'),
            "category": "World",
        },
        {
            "source": "CNBC",
            "url": source_value('POLYDATA_RSS_CNBC_URL'),
            "category": "Finance",
        },
        {
            "source": "Yahoo Finance",
            "url": source_value('POLYDATA_RSS_YAHOO_FINANCE_URL'),
            "category": "Finance",
        },
        {
            "source": "Financial Times",
            "url": source_value('POLYDATA_RSS_FINANCIAL_TIMES_URL'),
            "category": "Finance",
        },
        {
            "source": "Seeking Alpha",
            "url": source_value('POLYDATA_RSS_SEEKING_ALPHA_URL'),
            "category": "Finance",
        },
        {
            "source": "MarketWatch",
            "url": source_value('POLYDATA_RSS_MARKETWATCH_URL'),
            "category": "Finance",
        },
        {
            "source": "Bond Market",
            "url": source_value('POLYDATA_RSS_BOND_MARKET_URL'),
            "category": "Finance",
        },
        {
            "source": "Options Market",
            "url": source_value('POLYDATA_RSS_OPTIONS_MARKET_URL'),
            "category": "Finance",
        },
        {
            "source": "Economic Data",
            "url": source_value('POLYDATA_RSS_ECONOMIC_DATA_URL'),
            "category": "Macro",
        },
        {
            "source": "Oil & Gas",
            "url": source_value('POLYDATA_RSS_OIL_GAS_URL'),
            "category": "Energy",
        },
        {
            "source": "Reuters Energy",
            "url": source_value('POLYDATA_RSS_REUTERS_ENERGY_URL'),
            "category": "Energy",
        },
        {
            "source": "Gold & Metals",
            "url": source_value('POLYDATA_RSS_GOLD_METALS_URL'),
            "category": "Commodities",
        },
        {
            "source": "CoinDesk",
            "url": source_value('POLYDATA_RSS_COINDESK_URL'),
            "category": "Crypto",
        },
        {
            "source": "Cointelegraph",
            "url": source_value('POLYDATA_RSS_COINTELEGRAPH_URL'),
            "category": "Crypto",
        },
        {
            "source": "Decrypt",
            "url": source_value('POLYDATA_RSS_DECRYPT_URL'),
            "category": "Crypto",
        },
        {
            "source": "The Block",
            "url": source_value('POLYDATA_RSS_THE_BLOCK_URL'),
            "category": "Crypto",
        },
        {
            "source": "Blockworks",
            "url": source_value('POLYDATA_RSS_BLOCKWORKS_URL'),
            "category": "Crypto",
        },
        {
            "source": "The Defiant",
            "url": source_value('POLYDATA_RSS_THE_DEFIANT_URL'),
            "category": "Crypto",
        },
        {
            "source": "Bitcoin Magazine",
            "url": source_value('POLYDATA_RSS_BITCOIN_MAGAZINE_URL'),
            "category": "Crypto",
        },
        {
            "source": "Stablecoin Policy",
            "url": source_value('POLYDATA_RSS_STABLECOIN_POLICY_URL'),
            "category": "Crypto",
        },
        {
            "source": "Polymarket News",
            "url": source_value('POLYDATA_RSS_POLYMARKET_NEWS_URL'),
            "category": "Prediction Markets",
        },
        {
            "source": "Election Markets",
            "url": source_value('POLYDATA_RSS_ELECTION_MARKETS_URL'),
            "category": "Elections",
        },
        {
            "source": "Geopolitics Markets",
            "url": source_value('POLYDATA_RSS_GEOPOLITICS_MARKETS_URL'),
            "category": "Geopolitics",
        },
        {
            "source": "Macro Markets",
            "url": source_value('POLYDATA_RSS_MACRO_MARKETS_URL'),
            "category": "Macro",
        },
        {
            "source": "Tech Markets",
            "url": source_value('POLYDATA_RSS_TECH_MARKETS_URL'),
            "category": "Tech",
        },
        {
            "source": "TechCrunch",
            "url": source_value('POLYDATA_RSS_TECHCRUNCH_URL'),
            "category": "Tech",
        },
        {
            "source": "The Verge",
            "url": source_value('POLYDATA_RSS_THE_VERGE_URL'),
            "category": "Tech",
        },
        {
            "source": "MIT Tech Review",
            "url": source_value('POLYDATA_RSS_MIT_TECH_REVIEW_URL'),
            "category": "Tech",
        },
        {
            "source": "VentureBeat AI",
            "url": source_value('POLYDATA_RSS_VENTUREBEAT_AI_URL'),
            "category": "Tech",
        },
        {
            "source": "ArXiv AI",
            "url": source_value('POLYDATA_RSS_ARXIV_AI_URL'),
            "category": "Research",
        },
        {
            "source": "Semiconductor News",
            "url": source_value('POLYDATA_RSS_SEMICONDUCTOR_NEWS_URL'),
            "category": "Tech",
        },
        {
            "source": "ESPN",
            "url": source_value('POLYDATA_RSS_ESPN_NEWS_URL'),
            "category": "Sports",
        },
        {
            "source": "Cricket Markets",
            "url": source_value('POLYDATA_RSS_CRICKET_MARKETS_URL'),
            "category": "Sports",
        },
        {
            "source": "Esports Markets",
            "url": source_value('POLYDATA_RSS_ESPORTS_MARKETS_URL'),
            "category": "Esports",
        },
        {
            "source": "HLTV Counter-Strike",
            "url": source_value('POLYDATA_RSS_HLTV_COUNTER_STRIKE_URL'),
            "category": "Esports",
        },
        {
            "source": "Valorant Esports",
            "url": source_value('POLYDATA_RSS_VALORANT_ESPORTS_URL'),
            "category": "Esports",
        },
        {
            "source": "LoL Esports",
            "url": source_value('POLYDATA_RSS_LOL_ESPORTS_URL'),
            "category": "Esports",
        },
        {
            "source": "Dot Esports",
            "url": source_value('POLYDATA_RSS_DOT_ESPORTS_URL'),
            "category": "Esports",
        },
        {
            "source": "Sports Markets",
            "url": source_value('POLYDATA_RSS_SPORTS_MARKETS_URL'),
            "category": "Sports",
        },
        {
            "source": "NBA Markets",
            "url": source_value('POLYDATA_RSS_NBA_MARKETS_URL'),
            "category": "Sports",
        },
        {
            "source": "Tennis Markets",
            "url": source_value('POLYDATA_RSS_TENNIS_MARKETS_URL'),
            "category": "Sports",
        },
        {
            "source": "MLB Markets",
            "url": source_value('POLYDATA_RSS_MLB_MARKETS_URL'),
            "category": "Sports",
        },
        {
            "source": "UFC Markets",
            "url": source_value('POLYDATA_RSS_UFC_MARKETS_URL'),
            "category": "Sports",
        },
        {
            "source": "NBA Official",
            "url": source_value('POLYDATA_RSS_NBA_OFFICIAL_NEWS_URL'),
            "category": "Sports",
        },
        {
            "source": "ESPN NBA",
            "url": source_value('POLYDATA_RSS_ESPN_NBA_NEWS_URL'),
            "category": "Sports",
        },
        {
            "source": "The Athletic NBA",
            "url": source_value('POLYDATA_RSS_ATHLETIC_NBA_NEWS_URL'),
            "category": "Sports",
        },
        {
            "source": "Reuters Politics",
            "url": source_value('POLYDATA_RSS_REUTERS_POLITICS_URL'),
            "category": "Politics",
        },
        {
            "source": "AP Politics",
            "url": source_value('POLYDATA_RSS_AP_POLITICS_URL'),
            "category": "Politics",
        },
        {
            "source": "Election Polling",
            "url": source_value('POLYDATA_RSS_ELECTION_POLLING_URL'),
            "category": "Elections",
        },
        {
            "source": "Campaign Finance",
            "url": source_value('POLYDATA_RSS_CAMPAIGN_FINANCE_URL'),
            "category": "Elections",
        },
        {
            "source": "Crypto Regulation",
            "url": source_value('POLYDATA_RSS_CRYPTO_REGULATION_URL'),
            "category": "Crypto",
        },
        {
            "source": "Crypto Markets",
            "url": source_value('POLYDATA_RSS_CRYPTO_MARKETS_URL'),
            "category": "Crypto",
        },
        {
            "source": "Coinbase Blog",
            "url": source_value('POLYDATA_RSS_COINBASE_BLOG_URL'),
            "category": "Crypto",
        },
        {
            "source": "OpenAI News",
            "url": source_value('POLYDATA_RSS_OPENAI_NEWS_URL'),
            "category": "Tech",
        },
        {
            "source": "Google AI",
            "url": source_value('POLYDATA_RSS_GOOGLE_AI_NEWS_URL'),
            "category": "Tech",
        },
        {
            "source": "Anthropic News",
            "url": source_value('POLYDATA_RSS_ANTHROPIC_NEWS_URL'),
            "category": "Tech",
        },
        {
            "source": "AI Markets",
            "url": source_value('POLYDATA_RSS_AI_MARKETS_URL'),
            "category": "Research",
        },
        {
            "source": "Big Tech Markets",
            "url": source_value('POLYDATA_RSS_BIG_TECH_MARKETS_URL'),
            "category": "Tech",
        },
        {
            "source": "NHC Advisories",
            "url": source_value('POLYDATA_RSS_NHC_ADVISORIES_URL'),
            "category": "Weather",
        },
        {
            "source": "NOAA Weather",
            "url": source_value('POLYDATA_RSS_NOAA_WEATHER_URL'),
            "category": "Weather",
        },
        {
            "source": "Weather Markets",
            "url": source_value('POLYDATA_RSS_WEATHER_MARKETS_URL'),
            "category": "Weather",
        },
    ]


CONTENT_TOPIC_REGISTRY: List[Dict[str, object]] = [
    {
        "id": "prediction-markets",
        "label": "Prediction Markets",
        "categories": ["Prediction Markets"],
        "keywords": ["polymarket", "prediction market", "prediction markets", "kalshi", "forecasting"],
        "queries": [
            'Polymarket OR "prediction market" OR Kalshi when:3d',
            '"prediction markets" crypto politics sports when:7d',
        ],
    },
    {
        "id": "politics",
        "label": "Politics",
        "categories": ["Politics", "Government", "US"],
        "keywords": ["politics", "congress", "senate", "house", "trump", "biden", "white house"],
        "queries": [
            "US politics Congress White House election campaign when:2d",
            "Trump Biden Senate House Supreme Court policy when:2d",
        ],
    },
    {
        "id": "elections",
        "label": "Elections",
        "categories": ["Elections", "Politics"],
        "keywords": ["election", "poll", "polls", "nominee", "presidential", "senate race", "campaign"],
        "queries": [
            'election polls presidential campaign nominee "latest poll" when:2d',
            'senate poll governor poll primary campaign fundraising when:3d',
        ],
    },
    {
        "id": "sports",
        "label": "Sports",
        "categories": ["Sports"],
        "keywords": ["sports", "nba", "nfl", "mlb", "nhl", "ufc", "tennis", "cricket", "injury", "lineup"],
        "queries": [
            "NBA NFL MLB NHL UFC tennis cricket injury lineup odds when:1d",
            "sports injury report lineup starting pitcher odds when:1d",
        ],
    },
    {
        "id": "esports",
        "label": "Esports",
        "categories": ["Esports", "Sports"],
        "keywords": ["esports", "counter-strike", "counter strike", "cs2", "valorant", "league of legends", "dota", "kru", "1win", "betclic", "hltv"],
        "queries": [
            'esports Counter-Strike CS2 Valorant League of Legends Dota match roster when:3d',
            'site:hltv.org Counter-Strike CS2 esports match when:7d',
            'Valorant VCT esports match roster odds when:7d',
        ],
    },
    {
        "id": "nba",
        "label": "NBA",
        "categories": ["Sports"],
        "keywords": ["nba", "basketball", "knicks", "celtics", "thunder", "finals", "injury report"],
        "queries": [
            "NBA injury report lineup finals odds when:1d",
            "site:espn.com/nba NBA injury lineup when:2d",
            "site:nba.com NBA injury report finals when:2d",
        ],
    },
    {
        "id": "crypto",
        "label": "Crypto",
        "categories": ["Crypto"],
        "keywords": ["crypto", "bitcoin", "btc", "ethereum", "eth", "stablecoin", "solana", "defi"],
        "queries": [
            "crypto bitcoin ethereum stablecoin ETF regulation market when:1d",
            "bitcoin ETF flows ethereum solana defi when:1d",
        ],
    },
    {
        "id": "finance",
        "label": "Finance",
        "categories": ["Finance"],
        "keywords": ["stocks", "equities", "treasury", "yield", "market", "s&p", "nasdaq", "fed"],
        "queries": [
            "stocks treasury yields S&P Nasdaq Fed markets when:1d",
            "earnings market volatility VIX rates equities when:1d",
        ],
    },
    {
        "id": "macro",
        "label": "Macro",
        "categories": ["Macro", "Finance"],
        "keywords": ["macro", "inflation", "fed", "rates", "jobs", "unemployment", "gdp", "recession"],
        "queries": [
            "Fed inflation rates jobs GDP recession macro when:2d",
            "treasury yields unemployment GDP retail sales when:2d",
        ],
    },
    {
        "id": "cpi",
        "label": "CPI",
        "categories": ["Macro"],
        "keywords": ["cpi", "inflation", "core cpi", "headline cpi", "shelter", "oer"],
        "queries": [
            'CPI inflation "core CPI" shelter OER when:7d',
            '"inflation report" "consumer prices" Fed when:7d',
        ],
    },
    {
        "id": "oil-energy",
        "label": "Oil & Energy",
        "categories": ["Energy", "Commodities", "Macro"],
        "keywords": ["oil", "wti", "crude", "brent", "opec", "gas", "lng", "energy"],
        "queries": [
            'WTI "crude oil" Brent OPEC natural gas LNG when:2d',
            'oil prices energy markets gasoline diesel when:2d',
        ],
    },
    {
        "id": "geopolitics",
        "label": "Geopolitics",
        "categories": ["Geopolitics", "World", "Government"],
        "keywords": ["geopolitics", "war", "ceasefire", "sanctions", "iran", "israel", "ukraine", "russia", "taiwan"],
        "queries": [
            "war ceasefire sanctions Iran Israel Ukraine Russia Taiwan when:2d",
            "geopolitics conflict sanctions defense diplomacy when:2d",
        ],
    },
    {
        "id": "tech",
        "label": "Tech",
        "categories": ["Tech"],
        "keywords": ["tech", "technology", "apple", "tesla", "nvidia", "semiconductor", "chip", "spacex"],
        "queries": [
            "technology Apple Tesla Nvidia semiconductor chips when:2d",
            "big tech earnings antitrust product launch when:3d",
        ],
    },
    {
        "id": "ai",
        "label": "AI",
        "categories": ["Tech", "Research"],
        "keywords": ["ai", "openai", "anthropic", "gemini", "llm", "nvidia", "artificial intelligence"],
        "queries": [
            'AI OpenAI Anthropic Gemini LLM Nvidia "artificial intelligence" when:2d',
            'AI model launch benchmark regulation chips when:3d',
        ],
    },
    {
        "id": "weather",
        "label": "Weather",
        "categories": ["Weather", "World"],
        "keywords": ["weather", "hurricane", "storm", "temperature", "rain", "snow", "heat wave"],
        "queries": [
            "weather hurricane storm temperature heat wave when:2d",
            "NOAA hurricane forecast extreme weather rainfall snowfall when:2d",
        ],
    },
]


def non_empty_feeds(feeds: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [feed for feed in feeds if str(feed.get("url") or "").strip()]
