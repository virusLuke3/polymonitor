# Panel 环境配置检查清单

本清单按 `webpage/src/panels/modules/index.ts` 的 87 个注册模块逐项核对。状态仅表示源码配置检查，不代表上游实时可用、长期更新或所有频道能播放。

配置规范见 [私有来源配置规范](panel-env-configuration.md)。精确变量名和使用文件见 [来源变量索引](panel-env-source-bindings.json)，空值模板见 [`.env.example`](../.env.example)。同一拥有者的多个 Panel 复用一套配置和采集，不各自新增 worker。

| 序号 | 模块目录 | 标题 | 后端读取回调 / 共享方式 | 数据拥有者（services 下或注明路径） | 配置组 | 源码检查 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | [active-markets](../webpage/src/panels/modules/active-markets/index.tsx) | Active Markets | `共享页面资源 / 纯视图` | market_service.py / panel_trade_reader.py | POLYDATA_* 数据库、POLYDATA_POLYMARKET_*、共享 API | 已检查配置入口 |
| 2 | [global-orderfilled](../webpage/src/panels/modules/global-orderfilled/index.tsx) | Orderfilled Flow | `共享页面资源 / 纯视图` | clickhouse_orderfilled_service.py / alpha_signal_service.py | POLYDATA_ORDERFILLED_CLICKHOUSE_*；VITE_PUBLIC_EXPLORER_* | 已检查配置入口 |
| 3 | [oracle-feed](../webpage/src/panels/modules/oracle-feed/index.tsx) | Oracle Feed | `共享页面资源 / 纯视图` | query_service.py / panel_trade_reader.py | POLYMARKET_RPC_URL；共享数据库配置 | 已检查配置入口 |
| 4 | [market-summary](../webpage/src/panels/modules/market-summary/index.tsx) | Market Summary | `共享页面资源 / 纯视图` | market_service.py / panel_trade_reader.py | POLYDATA_* 数据库、POLYDATA_POLYMARKET_*、共享 API | 已检查配置入口 |
| 5 | [featured-market](../webpage/src/panels/modules/featured-market/index.tsx) | Market Context | `共享页面资源 / 纯视图` | market_service.py / panel_trade_reader.py | POLYDATA_* 数据库、POLYDATA_POLYMARKET_*、共享 API | 已检查配置入口 |
| 6 | [price-implications](../webpage/src/panels/modules/price-implications/index.tsx) | AI Insights | `共享页面资源 / 纯视图` | agent/common/ / 已有 market-insights 快照 | POLYDATA_AGENT_*；POLYDATA_TAVILY_SEARCH_URL；TAVILY_API_KEY | 已检查配置入口 |
| 7 | [price-chart](../webpage/src/panels/modules/price-chart/index.tsx) | Price Surface | `共享页面资源 / 纯视图` | market_service.py / panel_trade_reader.py | POLYDATA_* 数据库、POLYDATA_POLYMARKET_*、共享 API | 已检查配置入口 |
| 8 | [sample-chain-trades](../webpage/src/panels/modules/sample-chain-trades/index.tsx) | Special Radar | `共享页面资源 / 纯视图` | agent/common/ / 已有 market-insights 快照 | POLYDATA_AGENT_*；POLYDATA_TAVILY_SEARCH_URL；TAVILY_API_KEY | 已检查配置入口 |
| 9 | [oracle-timeline](../webpage/src/panels/modules/oracle-timeline/index.tsx) | Trend Watch | `共享页面资源 / 纯视图` | agent/common/ / 已有 market-insights 快照 | POLYDATA_AGENT_*；POLYDATA_TAVILY_SEARCH_URL；TAVILY_API_KEY | 已检查配置入口 |
| 10 | [related-news](../webpage/src/panels/modules/related-news/index.tsx) | Related Intelligence | `共享页面资源 / 纯视图` | free_content/ / content_runtime.py | POLYDATA_RSS_*；free_news_sources.json 的 ${变量名} | 已检查配置入口 |
| 11 | [breaking-event-radar](../webpage/src/panels/modules/breaking-event-radar/index.tsx) | Breaking Event Radar | `get_breaking_event_radar_snapshot` | breaking_event_radar_service.py | POLYDATA_GEO_SHOCK_*；RSS 配置 | 已检查配置入口 |
| 12 | [market-tv-wire](../webpage/src/panels/modules/market-tv-wire/index.tsx) | Market TV Wire | `get_market_tv_wire_snapshot` | live_video_source_service.py / trusted_hls_sources.py / youtube_* | live_video_sources.json 的 ${变量名}；POLYMONITOR_URL_*；VITE_PUBLIC_YOUTUBE_* | 已检查配置入口 |
| 13 | [market-youtube-channels](../webpage/src/panels/modules/market-youtube-channels/index.tsx) | YouTube Market TV | `get_market_youtube_channels_snapshot` | live_video_source_service.py / trusted_hls_sources.py / youtube_* | live_video_sources.json 的 ${变量名}；POLYMONITOR_URL_*；VITE_PUBLIC_YOUTUBE_* | 已检查配置入口 |
| 14 | [alpha-signal](../webpage/src/panels/modules/alpha-signal/index.tsx) | Alpha Signal | `get_alpha_signal_snapshot` | clickhouse_orderfilled_service.py / alpha_signal_service.py | POLYDATA_ORDERFILLED_CLICKHOUSE_*；VITE_PUBLIC_EXPLORER_* | 已检查配置入口 |
| 15 | [polysignal-feed](../webpage/src/panels/modules/polysignal-feed/index.tsx) | PolySignal | `get_polysignal_snapshot` | polysignal_feed_service.py / polysignal_agent_service.py | 共享成交数据库；POLYDATA_AGENT_* | 已检查配置入口 |
| 16 | [whale-tracker](../webpage/src/panels/modules/whale-tracker/index.tsx) | Whale Tracker | `get_whale_trades_snapshot` | clickhouse_orderfilled_service.py / alpha_signal_service.py | POLYDATA_ORDERFILLED_CLICKHOUSE_*；VITE_PUBLIC_EXPLORER_* | 已检查配置入口 |
| 17 | [suspicious-flow](../webpage/src/panels/modules/suspicious-flow/index.tsx) | Flow Watch | `get_suspicious_trades_snapshot` | clickhouse_orderfilled_service.py / alpha_signal_service.py | POLYDATA_ORDERFILLED_CLICKHOUSE_*；VITE_PUBLIC_EXPLORER_* | 已检查配置入口 |
| 18 | [commodities-watch](../webpage/src/panels/modules/commodities-watch/index.tsx) | Commodities Watch | `get_market_group_snapshot` | runtime_service.py / runtime/market_group_watcher.py | POLYDATA_YAHOO_CHART_BASE_URL；VITE_PUBLIC_COAL_ETF_SOURCE_URL | 已检查配置入口 |
| 19 | [crypto-watch](../webpage/src/panels/modules/crypto-watch/index.tsx) | Crypto Watch | `get_market_group_snapshot` | crypto_strategy/ | POLYMONITOR_URL_*；POLYDATA_CRYPTO_*；POLYMONITOR_SOURCE_ROUTES_JSON | 已检查配置入口 |
| 20 | [crypto-order-flow](../webpage/src/panels/modules/crypto-order-flow/index.tsx) | Crypto Order Flow | `get_crypto_strategy_snapshot` | crypto_strategy/ | POLYMONITOR_URL_*；POLYDATA_CRYPTO_*；POLYMONITOR_SOURCE_ROUTES_JSON | 已检查配置入口 |
| 21 | [crypto-oracle-reference](../webpage/src/panels/modules/crypto-oracle-reference/index.tsx) | Contract Reference | `get_crypto_strategy_snapshot` | crypto_strategy/native_reference.py | POLYDATA_CRYPTO_REFERENCE_*；MARKET_DATA_*；复用已有拥有者 | 已检查配置入口 |
| 22 | [options-implied-probability](../webpage/src/panels/modules/options-implied-probability/index.tsx) | Options Implied Probability | `get_crypto_strategy_snapshot` | crypto_strategy/ | POLYMONITOR_URL_*；POLYDATA_CRYPTO_*；POLYMONITOR_SOURCE_ROUTES_JSON | 已检查配置入口 |
| 23 | [crypto-exchange-inflow](../webpage/src/panels/modules/crypto-exchange-inflow/index.tsx) | Exchange Inflows | `get_crypto_strategy_snapshot` | crypto_strategy/ | POLYMONITOR_URL_*；POLYDATA_CRYPTO_*；POLYMONITOR_SOURCE_ROUTES_JSON | 已检查配置入口 |
| 24 | [ai-model-race](../webpage/src/panels/modules/ai-model-race/index.tsx) | AI MODEL RACE | `technology.panel_snapshot` | tech_panels_service.py | POLYDATA_YAHOO_CHART_BASE_URL；RSS；POLYMONITOR_URL_* | 已检查配置入口 |
| 25 | [big-tech-market-cap](../webpage/src/panels/modules/big-tech-market-cap/index.tsx) | BIG TECH CAP | `technology.panel_snapshot` | tech_panels_service.py | POLYDATA_YAHOO_CHART_BASE_URL；RSS；POLYMONITOR_URL_* | 已检查配置入口 |
| 26 | [consumer-app-pulse](../webpage/src/panels/modules/consumer-app-pulse/index.tsx) | APP PULSE | `technology.panel_snapshot` | tech_panels_service.py | POLYDATA_YAHOO_CHART_BASE_URL；RSS；POLYMONITOR_URL_* | 已检查配置入口 |
| 27 | [crypto-funding-watch](../webpage/src/panels/modules/crypto-funding-watch/index.tsx) | Crypto Funding Watch | `finance.crypto_funding_watch_snapshot` | crypto_funding/ / crypto_strategy/ | POLYDATA_CRYPTO_FUNDING_*；VITE_PUBLIC_*_FUNDING_URL | 已检查配置入口 |
| 28 | [defi-token-watch](../webpage/src/panels/modules/defi-token-watch/index.tsx) | DeFi Token Watch | `finance.defi_token_watch_snapshot` | defi_token_watch_service.py | POLYDATA_COINGECKO_BASE_URL；POLYDATA_API_HTTP_PROXY_URL | 已检查配置入口 |
| 29 | [defi-yield-monitor](../webpage/src/panels/modules/defi-yield-monitor/index.tsx) | DEFI YIELDS | `finance.watch_panel_snapshot` | finance_watch/ / finance_watch_panels_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；POLYDATA_RSS_* | 已检查配置入口 |
| 30 | [defi-security-watch](../webpage/src/panels/modules/defi-security-watch/index.tsx) | DEFI SECURITY | `finance.watch_panel_snapshot` | finance_watch/ / finance_watch_panels_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；POLYDATA_RSS_* | 已检查配置入口 |
| 31 | [crypto-perp-funding](../webpage/src/panels/modules/crypto-perp-funding/index.tsx) | Crypto Derivatives | `finance.watch_panel_snapshot` | crypto_strategy/ | POLYMONITOR_URL_*；POLYDATA_CRYPTO_*；POLYMONITOR_SOURCE_ROUTES_JSON | 已检查配置入口 |
| 32 | [tradfi-perp-radar](../webpage/src/panels/modules/tradfi-perp-radar/index.tsx) | TRADFI PERPS | `finance.watch_panel_snapshot` | finance_watch/ / finance_watch_panels_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；POLYDATA_RSS_* | 已检查配置入口 |
| 33 | [ipo-news-watch](../webpage/src/panels/modules/ipo-news-watch/index.tsx) | IPO NEWS | `finance.watch_panel_snapshot` | finance_watch/ / finance_watch_panels_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；POLYDATA_RSS_* | 已检查配置入口 |
| 34 | [broker-research-watch](../webpage/src/panels/modules/broker-research-watch/index.tsx) | BROKER RESEARCH | `finance.watch_panel_snapshot` | finance_watch/ / finance_watch_panels_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；POLYDATA_RSS_* | 已检查配置入口 |
| 35 | [global-index-monitor](../webpage/src/panels/modules/global-index-monitor/index.tsx) | GLOBAL INDICES | `finance.watch_panel_snapshot` | finance_watch/ / finance_watch_panels_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；POLYDATA_RSS_* | 已检查配置入口 |
| 36 | [commodity-equity-transmission](../webpage/src/panels/modules/commodity-equity-transmission/index.tsx) | Commodity Equity Transmission | `finance.commodity_equity_transmission_snapshot` | finance_panels_service.py / finance_external_sources_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；领域静态规则保留 | 已检查配置入口 |
| 37 | [crypto-fear-greed](../webpage/src/panels/modules/crypto-fear-greed/index.tsx) | FEAR & GREED | `finance.watch_panel_snapshot` | finance_watch/ / finance_watch_panels_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；POLYDATA_RSS_* | 已检查配置入口 |
| 38 | [crypto-etf-flow](../webpage/src/panels/modules/crypto-etf-flow/index.tsx) | CRYPTO ETF | `finance.watch_panel_snapshot` | finance_watch/ / finance_watch_panels_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；POLYDATA_RSS_* | 已检查配置入口 |
| 39 | [stablecoin-monitor](../webpage/src/panels/modules/stablecoin-monitor/index.tsx) | Stablecoin Pressure | `finance.watch_panel_snapshot` | crypto_strategy/ | POLYMONITOR_URL_*；POLYDATA_CRYPTO_*；POLYMONITOR_SOURCE_ROUTES_JSON | 已检查配置入口 |
| 40 | [blockchain-policy-news](../webpage/src/panels/modules/blockchain-policy-news/index.tsx) | CHAIN POLICY | `finance.watch_panel_snapshot` | finance_watch/ / finance_watch_panels_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；POLYDATA_RSS_* | 已检查配置入口 |
| 41 | [trade-policy-radar](../webpage/src/panels/modules/trade-policy-radar/index.tsx) | Trade Policy | `共享页面资源 / 纯视图` | finance_panels_service.py / finance_external_sources_service.py | POLYDATA_FINANCE_*；POLYDATA_YAHOO_*；领域静态规则保留 | 已检查配置入口 |
| 42 | [geo-sanctions-shock](../webpage/src/panels/modules/geo-sanctions-shock/index.tsx) | Geopolitical & Sanctions Shock | `world.geo_sanctions_shock_snapshot` | geo_sanctions_shock_service.py | POLYDATA_GEO_SHOCK_*；VITE_PUBLIC_OFAC_SOURCE_URL | 已检查配置入口 |
| 43 | [global-transport-shipping](../webpage/src/panels/modules/global-transport-shipping/index.tsx) | Global Transport / Shipping | `world.global_transport_shipping_snapshot` | global_transport_shipping_service.py | POLYDATA_OPENSKY_*；POLYDATA_AISSTREAM_*；POLYMONITOR_URL_* | 已检查配置入口 |
| 44 | [cpi-release-command-center](../webpage/src/panels/modules/cpi-release-command-center/index.tsx) | CPI Release Command Center | `macro.cpi_release_command_center_snapshot` | macro_cpi_panels_service.py | POLYDATA_MACRO_*；FRED_API_KEY；POLYMONITOR_URL_* | 已检查配置入口 |
| 45 | [cpi-components-pressure-registry](../webpage/src/panels/modules/cpi-components-pressure-registry/index.tsx) | CPI Components Pressure Registry | `macro.cpi_components_pressure_registry_snapshot` | macro_cpi_registry_service.py / macro_cpi_panels_service.py | POLYDATA_MACRO_*；FRED 配置；复用 CPI 拥有者 | 已检查配置入口 |
| 46 | [goods-tariff-supply-watch](../webpage/src/panels/modules/goods-tariff-supply-watch/index.tsx) | Goods / Tariff / Supply Chain Watch | `macro.goods_tariff_supply_watch_snapshot` | macro_cpi_registry_service.py / macro_cpi_panels_service.py | POLYDATA_MACRO_*；FRED 配置；复用 CPI 拥有者 | 已检查配置入口 |
| 47 | [labor-services-inflation-monitor](../webpage/src/panels/modules/labor-services-inflation-monitor/index.tsx) | Labor / Services Inflation Monitor | `macro.labor_services_inflation_monitor_snapshot` | macro_cpi_registry_service.py / macro_cpi_panels_service.py | POLYDATA_MACRO_*；FRED 配置；复用 CPI 拥有者 | 已检查配置入口 |
| 48 | [fed-reaction-growth-risk-board](../webpage/src/panels/modules/fed-reaction-growth-risk-board/index.tsx) | Fed Reaction / Growth Risk Board | `macro.fed_reaction_growth_risk_board_snapshot` | macro_cpi_registry_service.py / macro_cpi_panels_service.py | POLYDATA_MACRO_*；FRED 配置；复用 CPI 拥有者 | 已检查配置入口 |
| 49 | [polymarket-macro-map](../webpage/src/panels/modules/polymarket-macro-map/index.tsx) | Polymarket Macro Market Map | `macro.polymarket_macro_map_snapshot` | polymarket_macro_map_service.py | POLYDATA_MACRO_MARKET_MAP_SOURCE_URL；共享市场配置 | 已检查配置入口 |
| 50 | [cpi-release-calendar](../webpage/src/panels/modules/cpi-release-calendar/index.tsx) | CPI Release Calendar & Consensus Baseline | `macro.cpi_release_calendar_snapshot` | cpi_release_calendar_service.py / bls_calendar.py | 日历来源 POLYMONITOR_URL_*；复用宏观源 | 已检查配置入口 |
| 51 | [energy-gasoline-shock](../webpage/src/panels/modules/energy-gasoline-shock/index.tsx) | Energy & Gasoline Shock | `macro.energy_gasoline_shock_snapshot` | energy_gasoline_shock_service.py | FRED / Yahoo 配置；复用共享宏观拥有者 | 已检查配置入口 |
| 52 | [global-weather-map](../webpage/src/panels/modules/global-weather-map/index.tsx) | Global Temp Monitor | `get_global_weather_map_snapshot` | global_weather_map_service.py | 天气 POLYMONITOR_URL_*；POLYDATA_POLYMARKET_*；复用天气快照及盘口 | 已检查配置入口 |
| 53 | [weather-market-browser](../webpage/src/panels/modules/weather-market-browser/index.tsx) | Weather Market Browser | `get_global_weather_map_snapshot` | global_weather_map_service.py | 天气 POLYMONITOR_URL_*；POLYDATA_POLYMARKET_*；复用天气快照及盘口 | 已检查配置入口 |
| 54 | [weather-city-snapshot](../webpage/src/panels/modules/weather-city-snapshot/index.tsx) | Weather City Snapshot | `共享页面资源 / 纯视图` | global_weather_map_service.py | 天气 POLYMONITOR_URL_*；POLYDATA_POLYMARKET_*；复用天气快照及盘口 | 已检查配置入口 |
| 55 | [weather-quote-detail](../webpage/src/panels/modules/weather-quote-detail/index.tsx) | Weather Quote Curve | `共享页面资源 / 纯视图` | global_weather_map_service.py | 天气 POLYMONITOR_URL_*；POLYDATA_POLYMARKET_*；复用天气快照及盘口 | 已检查配置入口 |
| 56 | [weather-quote-table](../webpage/src/panels/modules/weather-quote-table/index.tsx) | Weather Quote Table | `共享页面资源 / 纯视图` | global_weather_map_service.py | 天气 POLYMONITOR_URL_*；POLYDATA_POLYMARKET_*；复用天气快照及盘口 | 已检查配置入口 |
| 57 | [weather-trend-detail](../webpage/src/panels/modules/weather-trend-detail/index.tsx) | Hourly forecast | `共享页面资源 / 纯视图` | global_weather_map_service.py | 天气 POLYMONITOR_URL_*；POLYDATA_POLYMARKET_*；复用天气快照及盘口 | 已检查配置入口 |
| 58 | [weather-trend-7d](../webpage/src/panels/modules/weather-trend-7d/index.tsx) | 7 day forecast | `共享页面资源 / 纯视图` | global_weather_map_service.py | 天气 POLYMONITOR_URL_*；POLYDATA_POLYMARKET_*；复用天气快照及盘口 | 已检查配置入口 |
| 59 | [weather-news](../webpage/src/panels/modules/weather-news/index.tsx) | Weather News | `get_weather_news_snapshot` | weather_news_service.py | POLYDATA_RSS_*；POLYMONITOR_URL_* | 已检查配置入口 |
| 60 | [world-clock](../webpage/src/panels/modules/world-clock/index.tsx) | World Clock | `共享页面资源 / 纯视图` | 浏览器时钟；无外部数据请求 | 不需要来源／密钥／代理 | 已检查配置入口 |
| 61 | [food-retail-basket-pressure](../webpage/src/panels/modules/food-retail-basket-pressure/index.tsx) | Food & Retail Basket Pressure | `共享页面资源 / 纯视图` | food_retail_basket_service.py | 共享 FRED 配置；POLYMONITOR_URL_* | 已检查配置入口 |
| 62 | [supply-tariff-import-watch](../webpage/src/panels/modules/supply-tariff-import-watch/index.tsx) | Supply Tariff Import Watch | `macro.supply_tariff_import_watch_snapshot` | macro_cpi_panels_service.py | 复用 CPI / FRED / 市场配置 | 已检查配置入口 |
| 63 | [shelter-rent-oer-pressure](../webpage/src/panels/modules/shelter-rent-oer-pressure/index.tsx) | Shelter Rent OER Pressure | `macro.shelter_rent_oer_pressure_snapshot` | macro_cpi_panels_service.py | 复用 CPI / FRED / 市场配置 | 已检查配置入口 |
| 64 | [labor-wage-services-pressure](../webpage/src/panels/modules/labor-wage-services-pressure/index.tsx) | Labor Wage Services Pressure | `macro.labor_wage_services_pressure_snapshot` | macro_cpi_panels_service.py | 复用 CPI / FRED / 市场配置 | 已检查配置入口 |
| 65 | [growth-demand-recession-tracker](../webpage/src/panels/modules/growth-demand-recession-tracker/index.tsx) | Growth Demand Recession Tracker | `macro.growth_demand_recession_tracker_snapshot` | macro_cpi_panels_service.py | 复用 CPI / FRED / 市场配置 | 已检查配置入口 |
| 66 | [fed-rates-polymarket-gap](../webpage/src/panels/modules/fed-rates-polymarket-gap/index.tsx) | Fed Rates Polymarket Gap | `macro.fed_rates_polymarket_gap_snapshot` | macro_cpi_panels_service.py | 复用 CPI / FRED / 市场配置 | 已检查配置入口 |
| 67 | [nba-scoreboard](../webpage/src/panels/modules/nba-scoreboard/index.tsx) | NBA Scoreboard | `sports.nba_scoreboard_snapshot` | runtime_service.py / scripts/NBA/ | POLYDATA_ESPN_*；POLYDATA_NBA_* | 已检查配置入口 |
| 68 | [nba-intel](../webpage/src/panels/modules/nba-intel/index.tsx) | NBA Intel | `sports.nba_intel_snapshot` | runtime_service.py / scripts/NBA/ | POLYDATA_ESPN_*；POLYDATA_NBA_* | 已检查配置入口 |
| 69 | [espn-matchup-predictor](../webpage/src/panels/modules/espn-matchup-predictor/index.tsx) | ESPN Matchup Predictor | `sports.nba_matchup_predictor_snapshot` | runtime_service.py / scripts/NBA/ | POLYDATA_ESPN_*；POLYDATA_NBA_* | 已检查配置入口 |
| 70 | [esports-intel](../webpage/src/panels/modules/esports-intel/index.tsx) | Esports Intel | `sports.grid_esports_snapshot` | grid_esports_service.py | POLYDATA_GRID_*；GRID_API_KEY | 已检查配置入口 |
| 71 | [sports-odds](../webpage/src/panels/modules/sports-odds/index.tsx) | Sports Odds | `sports.sports_odds_snapshot` | sports_odds_service.py | POLYDATA_THE_ODDS_*；POLYDATA_THERUNDOWN_*；POLYDATA_API_FOOTBALL_* | 已检查配置入口 |
| 72 | [inflation-nowcast](../webpage/src/panels/modules/inflation-nowcast/index.tsx) | Inflation Nowcast | `macro.inflation_nowcast_snapshot` | runtime_service.py / runtime/inflation_nowcast_watcher.py | POLYDATA_CLEVELAND_FED_NOWCAST_URL；共享宏观源 | 已检查配置入口 |
| 73 | [jin10-flash](../webpage/src/panels/modules/jin10-flash/index.tsx) | Jin10 Flash | `macro.jin10_panel_snapshot` | scripts/jin10/flash_client.py | POLYDATA_JIN10_*；POLYDATA_API_HTTP_PROXY_URL | 已检查配置入口 |
| 74 | [new-market-signals](../webpage/src/panels/modules/new-market-signals/index.tsx) | New Market Signals | `get_new_market_signals_snapshot` | new_market_signal_service.py / runtime/new_market_signal_watcher.py | POLYDATA_POLYMARKET_*；现有市场拥有者 | 已检查配置入口 |
| 75 | [lob-depth](../webpage/src/panels/modules/lob-depth/index.tsx) | LOB Depth | `共享页面资源 / 纯视图` | lob_service.py | MARKET_DATA_LOB_URL；复用 market-data，无新采集器 | 已检查配置入口 |
| 76 | [f1-trackside](../webpage/src/panels/modules/f1-trackside/index.tsx) | BWE News | `sports.f1_panel_snapshot` | scripts/f1/runtime_feed.py | POLYDATA_F1_BWENEWS_*；POLYDATA_API_HTTP_PROXY_URL | 已检查配置入口 |
| 77 | [company-events](../webpage/src/panels/modules/company-events/index.tsx) | Company Events | `get_official_disclosures_snapshot` | official_disclosures_service.py / official_disclosures_watcher.py | POLYMONITOR_SEC_USER_AGENT；POLYMONITOR_DISCLOSURES_*；POLYMONITOR_URL_* | 已检查配置入口 |
| 78 | [policy-progress](../webpage/src/panels/modules/policy-progress/index.tsx) | Policy Progress | `get_official_disclosures_snapshot` | official_disclosures_service.py / politics/ | Federal Register / Congress 配置；POLYMONITOR_POLITICS_* | 已检查配置入口 |
| 79 | [politics-election](../webpage/src/panels/modules/politics-election/index.tsx) | Election Watch | `get_politics_snapshot` | politics/ / official_disclosures_service.py | POLYMONITOR_URL_*；POLYMONITOR_FEC_BULK_REDIRECT_URL；POLYMONITOR_POLITICS_*；AP / Congress / FEC 可选密钥 | 已检查配置入口 |
| 80 | [politics-early-vote](../webpage/src/panels/modules/politics-early-vote/index.tsx) | Early Vote | `get_politics_snapshot` | politics/ / official_disclosures_service.py | POLYMONITOR_URL_*；POLYMONITOR_FEC_BULK_REDIRECT_URL；POLYMONITOR_POLITICS_*；AP / Congress / FEC 可选密钥 | 已检查配置入口 |
| 81 | [politics-nomination](../webpage/src/panels/modules/politics-nomination/index.tsx) | Nomination Path | `get_politics_snapshot` | politics/ / official_disclosures_service.py | POLYMONITOR_URL_*；POLYMONITOR_FEC_BULK_REDIRECT_URL；POLYMONITOR_POLITICS_*；AP / Congress / FEC 可选密钥 | 已检查配置入口 |
| 82 | [politics-seats](../webpage/src/panels/modules/politics-seats/index.tsx) | Seat Balance | `get_politics_snapshot` | politics/ / official_disclosures_service.py | POLYMONITOR_URL_*；POLYMONITOR_FEC_BULK_REDIRECT_URL；POLYMONITOR_POLITICS_*；AP / Congress / FEC 可选密钥 | 已检查配置入口 |
| 83 | [politics-campaign-finance](../webpage/src/panels/modules/politics-campaign-finance/index.tsx) | Campaign Finance | `get_politics_snapshot` | politics/ / official_disclosures_service.py | POLYMONITOR_URL_*；POLYMONITOR_FEC_BULK_REDIRECT_URL；POLYMONITOR_POLITICS_*；AP / Congress / FEC 可选密钥 | 已检查配置入口 |
| 84 | [politics-government](../webpage/src/panels/modules/politics-government/index.tsx) | Government Formation | `get_politics_snapshot` | politics/ / official_disclosures_service.py | POLYMONITOR_URL_*；POLYMONITOR_FEC_BULK_REDIRECT_URL；POLYMONITOR_POLITICS_*；AP / Congress / FEC 可选密钥 | 已检查配置入口 |
| 85 | [politics-executive](../webpage/src/panels/modules/politics-executive/index.tsx) | Executive Actions | `get_politics_snapshot` | politics/ / official_disclosures_service.py | POLYMONITOR_URL_*；POLYMONITOR_FEC_BULK_REDIRECT_URL；POLYMONITOR_POLITICS_*；AP / Congress / FEC 可选密钥 | 已检查配置入口 |
| 86 | [politics-appointments](../webpage/src/panels/modules/politics-appointments/index.tsx) | Appointments | `get_politics_snapshot` | politics/ / official_disclosures_service.py | POLYMONITOR_URL_*；POLYMONITOR_FEC_BULK_REDIRECT_URL；POLYMONITOR_POLITICS_*；AP / Congress / FEC 可选密钥 | 已检查配置入口 |
| 87 | [politics-funding](../webpage/src/panels/modules/politics-funding/index.tsx) | Funding Deadline | `get_politics_snapshot` | politics/ / official_disclosures_service.py | POLYMONITOR_URL_*；POLYMONITOR_FEC_BULK_REDIRECT_URL；POLYMONITOR_POLITICS_*；AP / Congress / FEC 可选密钥 | 已检查配置入口 |

## 额外共享入口

- 地图：`natural_hazards/providers/`、`global_transport_shipping_service.py`、`map_infrastructure_service.py` 的来源入口也迁入环境配置；浏览器底图、雷达使用明确的 `VITE_PUBLIC_*`。
- 已有后端 Finance Liquidity、Market Atlas、World Cup、Equity Event 等接口使用相同已检查的共享拥有者，不因未在 87 个默认模块里而保留硬编码来源。
- 代理：`POLYMONITOR_SOURCE_ROUTES_JSON` 保存来源主机到已授权出口的顺序；来源级代理、SSH 目标、密钥路径、监听地址通过环境配置。未切换主 Clash，未启用已停用通道。
- 市场与链上：已有数据库、RPC、LOB、position snapshot 数据来源仍由对应拥有者管理；本次只改配置读取。
- 固定协议标识（XML/SVG namespace）、解析字段、业务 ID、证券代码、来源名称、安全校验规则及版权署名不是请求入口，保留原义。响应中的证据链接、分页和临时媒体地址仍由原校验处理。

## 配置与运行边界

Python 的 `source_value()` 只读显式进程环境或 `POLYMONITOR_ENV_FILE` 指定的私有文件，默认项目 `.env`。进程值优先，显式空值禁用该入口；不再隐式合并 `.env.local` 或 `scripts/.env`。修改私有配置后按对应拥有者生命周期重载，不更改数据周期或存储身份。

JSON 目录使用 `${ENV_NAME}`。`.env.example` 不提供真实来源或代理地址。前端只构建明确公开的来源 URL 与已有 API/地图公共参数，密钥和代理配置不进入前端环境对象。

测试通过独立公开 fixture 配置模拟请求，不读取个人 `.env`。源码检查、单元测试、实际服务配置生效和长期采集健康是不同验收项，运行验证记录应另列证据。


## 本次验收记录（2026-11-06）

- 配置迁移代码：`69c8caec8fe5e3f2d89e6cc5844076885bd3b37b`，已推送。前端从该提交的干净 archive、Node 22.23.3 构建；仅注入公开配置，并检查构建产物未包含私有密钥值。
- 前端：服务器和实际 www 页面 `/release-sha` 均与该提交一致。使用真实 API、瓦片和默认主页取得桌面及手机截图，保留在本机 `artifacts/panel-env/`。此次主页呈现 77 个现有默认布局槽位；注册表的 87 个模块是源码检查范围，两个数量不能混为一谈。
- 后端：以本次变更为增量合并 60 个运行文件，保留运行目录原有其他修改。32 个运行中的 API／数据进程确认 `POLYMONITOR_ENV_FILE` 指向项目私有配置；未启动已停止的服务。来源／代理配置相关导入与解析错误未出现。`/health`、`/runtime/politics/election`、`/runtime/markets/crypto` 抽查为 200。
- 自动检查：后端相关测试 398 项通过，随后新增两项覆盖“禁止写死来源”及“注册 Panel／示例变量完整性”的检查通过；前端 397 项通过、1 项原有跳过。构建、源码解析、迁移变量完整性和本次提交的密钥扫描通过。
- **未计为通过的部分**：生产截图仍有 Panel 处于加载状态，手机地图未加载完成；随后浏览器复测出现 `ERR_NETWORK_CHANGED`。取得新版本与截图不等于所有 Panel 内容完成加载，更不等于上游连续采集健康。本次没有更改刷新周期、布局、主 Clash 或来源选择来绕过这些现象。
- 私有 `.env` 权限为 0600、受 Git 忽略；原有个人值保留。必要的临时构建／合并目录均已清理，未保存一次性探测脚本。


### 最终复核补充

移除开发服务器的隐式地址回退后，前端重新从已推送提交 `a049637cb0f3bac839578e6a7ddcc8675bfb2a2c` 的干净 archive 构建并部署，远端与浏览器的版本号一致。最终桌面复测中 Election Watch 的 Runtime 为 `ready`，显示真实民调和选区数据，字体状态为 `loaded`，地图没有出现重载错误入口。截图已更新。

首次手机截图取得的是前一发布版本；最终版本的手机复测连续三次导航失败，因此不能算作最新版本的手机验收通过。此前的加载态、网络中断和字体等待超时分别记录，不能据此宣称所有 Panel 持续健康。最终检查未发现本次提交包含密钥；任务临时构建、合并与 SSH 控制目录无残留。
