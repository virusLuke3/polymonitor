import { panel as external0 } from './geo-conflict-watch';
import { panel as external1 } from './geo-ceasefire-watch';
import { panel as external2 } from './geo-territory-control';
import { panel as external3 } from './geo-diplomacy-calendar';
import { panel as external4 } from './geo-treaty-tracker';
import { panel as external5 } from './weather-precipitation';
import { panel as external6 } from './weather-drought';
import { panel as external7 } from './weather-extremes';
import { panel as external8 } from './weather-storm-advisory';
import { panel as external9 } from './sports-spread-monitor';
import { panel as external10 } from './sports-total-monitor';
import { panel as external11 } from './sports-player-props';
import { panel as external12 } from './sports-tournament-path';
import { panel as external13 } from './sports-season-race';
import { panel as external14 } from './sports-awards-watch';
import { panel as external15 } from './esports-map-state';
import { panel as external16 } from './esports-tournament-path';
import { panel as external17 } from './crypto-listing-watch';
import { panel as external18 } from './crypto-project-milestones';
import { panel as external19 } from './chain-metrics-monitor';
import { panel as external20 } from './fiscal-tax-monitor';
import { panel as external21 } from './merger-progress';
import { panel as external22 } from './private-valuation-watch';
import { panel as external23 } from './ai-leaderboard-watch';
import { panel as external24 } from './art-auction-watch';
import { panel as external25 } from './culture-box-office';
import { panel as external26 } from './culture-awards-race';
import { panel as external27 } from './culture-music-charts';
import { panel as external28 } from './product-release-watch';
import { panel as external29 } from './public-figure-events';
import { panel as external30 } from './reality-show-progress';
import { panel as external31 } from './research-evidence-watch';
import { panel as external32 } from './social-window-monitor';
import { panel as external33 } from './space-mission-watch';
import { panel as external34 } from './mentions-evidence';
import type { PanelModule } from '../types';
import { panel as activeMarkets } from './active-markets';
import { panel as globalOrderfilled } from './global-orderfilled';
import { panel as oracleFeed } from './oracle-feed';
import { panel as marketSummary } from './market-summary';
import { panel as featuredMarket } from './featured-market';
import { panel as priceImplications } from './price-implications';
import { panel as priceChart } from './price-chart';
import { panel as sampleChainTrades } from './sample-chain-trades';
import { panel as oracleTimeline } from './oracle-timeline';
import { panel as relatedNews } from './related-news';
import { panel as breakingEventRadar } from './breaking-event-radar';
import { panel as marketTvWire } from './market-tv-wire';
import { panel as marketYoutubeChannels } from './market-youtube-channels';
import { panel as alphaSignal } from './alpha-signal';
import { panel as whaleTracker } from './whale-tracker';
import { panel as suspiciousFlow } from './suspicious-flow';
import { panel as commoditiesWatch } from './commodities-watch';
import { panel as cryptoWatch } from './crypto-watch';
import { panel as cryptoOrderFlow } from './crypto-order-flow';
import { panel as cryptoOracleReference } from './crypto-oracle-reference';
import { panel as optionsImpliedProbability } from './options-implied-probability';
import { panel as cryptoExchangeInflow } from './crypto-exchange-inflow';
import { panel as aiModelRace } from './ai-model-race';
import { panel as bigTechMarketCap } from './big-tech-market-cap';
import { panel as consumerAppPulse } from './consumer-app-pulse';
import { panel as cryptoFundingWatch } from './crypto-funding-watch';
import { panel as defiTokenWatch } from './defi-token-watch';
import { panel as defiYieldMonitor } from './defi-yield-monitor';
import { panel as defiSecurityWatch } from './defi-security-watch';
import { panel as cryptoPerpFunding } from './crypto-perp-funding';
import { panel as tradfiPerpRadar } from './tradfi-perp-radar';
import { panel as ipoNewsWatch } from './ipo-news-watch';
import { panel as brokerResearchWatch } from './broker-research-watch';
import { panel as globalIndexMonitor } from './global-index-monitor';
import { panel as commodityEquityTransmission } from './commodity-equity-transmission';
import { panel as cryptoFearGreed } from './crypto-fear-greed';
import { panel as cryptoEtfFlow } from './crypto-etf-flow';
import { panel as stablecoinMonitor } from './stablecoin-monitor';
import { panel as blockchainPolicyNews } from './blockchain-policy-news';
import { panel as tradePolicyRadar } from './trade-policy-radar';
import { panel as geoSanctionsShock } from './geo-sanctions-shock';
import { panel as globalTransportShipping } from './global-transport-shipping';
import { panel as cpiReleaseCommandCenter } from './cpi-release-command-center';
import { panel as cpiComponentsPressureRegistry } from './cpi-components-pressure-registry';
import { panel as goodsTariffSupplyWatch } from './goods-tariff-supply-watch';
import { panel as laborServicesInflationMonitor } from './labor-services-inflation-monitor';
import { panel as fedReactionGrowthRiskBoard } from './fed-reaction-growth-risk-board';
import { panel as polymarketMacroMap } from './polymarket-macro-map';
import { panel as cpiReleaseCalendar } from './cpi-release-calendar';
import { panel as energyGasolineShock } from './energy-gasoline-shock';
import { panel as globalTemperatureMonitor } from './global-weather-map';
import { panel as weatherMarketBrowser } from './weather-market-browser';
import { panel as weatherCitySnapshot } from './weather-city-snapshot';
import { panel as weatherQuoteDetail } from './weather-quote-detail';
import { panel as weatherQuoteTable } from './weather-quote-table';
import { panel as weatherTrendDetail } from './weather-trend-detail';
import { panel as weatherTrend7d } from './weather-trend-7d';
import { panel as weatherNews } from './weather-news';
import { panel as worldClock } from './world-clock';
import { panel as foodRetailBasketPressure } from './food-retail-basket-pressure';
import { panel as supplyTariffImportWatch } from './supply-tariff-import-watch';
import { panel as shelterRentOerPressure } from './shelter-rent-oer-pressure';
import { panel as laborWageServicesPressure } from './labor-wage-services-pressure';
import { panel as growthDemandRecessionTracker } from './growth-demand-recession-tracker';
import { panel as fedRatesPolymarketGap } from './fed-rates-polymarket-gap';
import { panel as nbaScoreboard } from './nba-scoreboard';
import { panel as nbaIntel } from './nba-intel';
import { panel as espnMatchupPredictor } from './espn-matchup-predictor';
import { panel as esportsIntel } from './esports-intel';
import { panel as sportsOdds } from './sports-odds';
import { panel as inflationNowcast } from './inflation-nowcast';
import { panel as jin10Flash } from './jin10-flash';
import { panel as newMarketSignals } from './new-market-signals';
import { panel as lobDepth } from './lob-depth';
import { panel as f1Trackside } from './f1-trackside';
import { panel as companyEvents } from './company-events';
import { panel as policyProgress } from './policy-progress';
import { panel as politicsElection } from './politics-election';
import { panel as politicsEarlyVote } from './politics-early-vote';
import { panel as politicsNomination } from './politics-nomination';
import { panel as politicsSeats } from './politics-seats';
import { panel as politicsCampaignFinance } from './politics-campaign-finance';
import { panel as politicsGovernment } from './politics-government';
import { panel as politicsExecutive } from './politics-executive';
import { panel as politicsAppointments } from './politics-appointments';
import { panel as politicsFunding } from './politics-funding';
export const PANEL_MODULES: PanelModule[] = [
  activeMarkets,
  globalOrderfilled,
  oracleFeed,
  marketSummary,
  featuredMarket,
  priceImplications,
  priceChart,
  sampleChainTrades,
  oracleTimeline,
  relatedNews,
  breakingEventRadar,
  marketTvWire,
  marketYoutubeChannels,
  alphaSignal,
  whaleTracker,
  suspiciousFlow,
  commoditiesWatch,
  cryptoWatch,
  cryptoOrderFlow,
  cryptoOracleReference,
  optionsImpliedProbability,
  cryptoExchangeInflow,
  aiModelRace,
  bigTechMarketCap,
  consumerAppPulse,
  cryptoFundingWatch,
  defiTokenWatch,
  defiYieldMonitor,
  defiSecurityWatch,
  cryptoPerpFunding,
  tradfiPerpRadar,
  ipoNewsWatch,
  brokerResearchWatch,
  globalIndexMonitor,
  commodityEquityTransmission,
  cryptoFearGreed,
  cryptoEtfFlow,
  stablecoinMonitor,
  blockchainPolicyNews,
  tradePolicyRadar,
  geoSanctionsShock,
  globalTransportShipping,
  cpiReleaseCommandCenter,
  cpiComponentsPressureRegistry,
  goodsTariffSupplyWatch,
  laborServicesInflationMonitor,
  fedReactionGrowthRiskBoard,
  polymarketMacroMap,
  cpiReleaseCalendar,
  energyGasolineShock,
  globalTemperatureMonitor,
  weatherMarketBrowser,
  weatherCitySnapshot,
  weatherQuoteDetail,
  weatherQuoteTable,
  weatherTrendDetail,
  weatherTrend7d,
  weatherNews,
  worldClock,
  foodRetailBasketPressure,
  supplyTariffImportWatch,
  shelterRentOerPressure,
  laborWageServicesPressure,
  growthDemandRecessionTracker,
  inflationNowcast,
  fedRatesPolymarketGap,
  nbaScoreboard,
  nbaIntel,
  espnMatchupPredictor,
  esportsIntel,
  sportsOdds,
  jin10Flash,
  newMarketSignals,
  lobDepth,
  f1Trackside,
  companyEvents,
  policyProgress,
  politicsElection,
  politicsEarlyVote,
  politicsNomination,
  politicsSeats,
  politicsCampaignFinance,
  politicsGovernment,
  politicsExecutive,
  politicsAppointments,
  politicsFunding,

  external0,
  external1,
  external2,
  external3,
  external4,
  external5,
  external6,
  external7,
  external8,
  external9,
  external10,
  external11,
  external12,
  external13,
  external14,
  external15,
  external16,
  external17,
  external18,
  external19,
  external20,
  external21,
  external22,
  external23,
  external24,
  external25,
  external26,
  external27,
  external28,
  external29,
  external30,
  external31,
  external32,
  external33,
  external34,
];
