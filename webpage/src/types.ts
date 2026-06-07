export type MarketSummary = {
  id: number;
  slug: string;
  title: string;
  conditionId?: string | null;
  questionId?: string | null;
  oracle?: string | null;
  yesTokenId?: string | null;
  noTokenId?: string | null;
  description?: string;
  status?: string;
  latestPrice?: string | number | null;
  latestYesPrice?: string | number | null;
  latestNoPrice?: string | number | null;
  enableNegRisk?: boolean;
  endDate?: string | null;
  createdAt?: string | null;
  category?: string;
  tags?: string[];
  gammaMarketId?: string | number | null;
};

export type BootstrapPayload = {
  generatedAt: string;
  defaultWorkspace: {
    name: string;
    panels: string[];
  };
  featuredMarket: MarketSummary | null;
  activeMarketsPreview: MarketListItem[];
  activeMarketGroupsPreview?: MarketGroupItem[];
  globalTradesPreview: TradeRow[];
  globalOraclePreview: OracleEvent[];
  latestContentPreview: ContentItem[];
  commoditiesPreview?: RuntimeMarketGroup | null;
  recentTradesPreview: TradeRow[];
  oraclePreview: OracleEvent[];
  contentPreview: ContentItem[];
  pricePreview: PriceSummary | null;
  systemHealth: SystemHealth;
};

export type MarketsPayload = {
  items: MarketListItem[];
  pagination: {
    page: number;
    pageSize: number;
    total: number;
    totalPages: number;
    hasMore: boolean;
  };
};

export type MarketGroupOutcome = {
  outcomeKey?: string | null;
  marketId?: number | null;
  gammaMarketId?: string | number | null;
  label?: string | null;
  title?: string | null;
  yesPrice?: string | number | null;
  noPrice?: string | number | null;
  change24h?: string | number | null;
  volume24h?: string | number | null;
  tradeCount24h?: number | string | null;
  lastTradeAt?: string | null;
  conditionId?: string | null;
  slug?: string | null;
  yesTokenId?: string | null;
  noTokenId?: string | null;
};

export type MarketGroupItem = {
  groupId: string;
  eventId?: string | number | null;
  title: string;
  slug?: string | null;
  category?: string | null;
  tags?: string[];
  createdAt?: string | null;
  endDate?: string | null;
  volume24h?: string | number | null;
  tradeCount24h?: number | string | null;
  outcomeCount?: number | null;
  defaultOutcomeKey?: string | null;
  defaultMarketId?: number | null;
  outcomes: MarketGroupOutcome[];
  topOutcomes: MarketGroupOutcome[];
};

export type MarketGroupSort = 'active' | 'new' | 'volume';
export type MarketGroupChartRange = '1h' | '6h' | '1d' | '1w' | '1m' | 'all';

export type MarketGroupsPayload = {
  items: MarketGroupItem[];
  pagination: {
    page: number;
    pageSize: number;
    total?: number;
    totalPages?: number;
    hasMore: boolean;
  };
  generatedAt?: string;
};

export type MarketGroupDetail = MarketGroupItem & {
  defaultOutcomeKey?: string | null;
  generatedAt?: string;
  status?: string;
};

export type MarketGroupChartSeriesPoint = {
  timestamp: string;
  price: number | string;
};

export type MarketGroupChartSeries = {
  outcomeKey?: string | null;
  label?: string | null;
  marketId?: number | null;
  color?: string | null;
  points: MarketGroupChartSeriesPoint[];
};

export type MarketGroupChartPayload = {
  eventId?: string | number | null;
  groupId?: string | null;
  title?: string | null;
  defaultOutcomeKey?: string | null;
  range: string;
  interval?: string | null;
  historyStatus?: string | null;
  generatedAt?: string;
  series: MarketGroupChartSeries[];
};

export type MarketListItem = {
  id: number;
  slug: string;
  title: string;
  conditionId?: string | null;
  questionId?: string | null;
  gammaMarketId?: string | number | null;
  endDate?: string | null;
  createdAt?: string | null;
  latestPrice?: string | number | null;
  status?: string;
  category?: string;
  tags?: string[];
  outcomeCount?: number | null;
  volume24h?: string | number | null;
  tradeCount24h?: number | null;
  change24h?: string | number | null;
  lastTradeAt?: string | null;
};

export type TradeRow = {
  txHash?: string | null;
  logIndex?: number | null;
  blockNumber?: number | null;
  timestamp?: string | null;
  maker?: string | null;
  taker?: string | null;
  price?: string | null;
  size?: string | null;
  side?: string | null;
  outcome?: string | null;
  tokenId?: string | null;
  marketId?: number | null;
  marketTitle?: string | null;
  orderHash?: string | null;
  makerAssetId?: string | null;
  takerAssetId?: string | null;
  makerAmount?: string | number | null;
  takerAmount?: string | number | null;
  fee?: string | number | null;
  contract?: string | null;
};

export type OracleEvent = {
  id?: number;
  txHash?: string | null;
  blockNumber?: number | null;
  eventTime?: string | null;
  eventStatus?: string | null;
  externalMarketId?: string | null;
  marketId?: number | null;
  localMarketId?: number | null;
  gammaMarketId?: string | number | null;
  marketTitle?: string | null;
  marketSlug?: string | null;
  marketCategory?: string | null;
  isBound?: boolean | null;
  matchedBy?: string | null;
  questionId?: string | null;
  conditionId?: string | null;
  proposedPrice?: string | number | null;
  settledPrice?: string | number | null;
  payout?: string | number | null;
  settlementCode?: number | string | null;
  settlementOutcome?: string | null;
  settlementSource?: string | null;
  settlementRaw?: string | null;
  effectiveSettlementCode?: number | string | null;
  effectiveSettlementOutcome?: string | null;
  effectiveSettlementSource?: string | null;
  completionStatus?: string | null;
  isTradingClosed?: boolean | null;
  isResolved?: boolean | null;
  isFinal?: boolean | null;
  requester?: string | null;
  proposer?: string | null;
  disputer?: string | null;
  proposalTransaction?: string | null;
  settlementTransaction?: string | null;
  sourceAdapter?: string | null;
  sourceOracle?: string | null;
};

export type OraclePayload = {
  marketId: number;
  localMarketId?: number | null;
  gammaMarketId?: string | number | null;
  questionId?: string | null;
  conditionId?: string | null;
  oracle?: string | null;
  currentStatus?: string | null;
  completionStatus?: string | null;
  isTradingClosed?: boolean | null;
  isResolved?: boolean | null;
  isFinal?: boolean | null;
  settlementOutcome?: string | null;
  settlementSource?: string | null;
  timeline: OracleEvent[];
};

export type PriceSummary = {
  marketId: number;
  latestPrice?: string | null;
  latestYesPrice?: string | null;
  latestNoPrice?: string | null;
  change1h?: string | null;
  change24h?: string | null;
  volume24h?: string | null;
  tradeCount24h?: number;
  updatedAt?: string | null;
};

export type ChartPoint = {
  timestamp: string;
  yesPrice?: string | number | null;
  noPrice?: string | number | null;
  value?: string | number | null;
};

export type ChartPayload = {
  marketId: number;
  localMarketId?: number | null;
  range: string;
  interval: string;
  kind?: 'probability' | 'underlying-price' | string;
  historyStatus?: 'ok' | 'short' | 'flat' | 'snapshot' | 'missing' | string | null;
  sourceSymbol?: string | null;
  sourceLabel?: string | null;
  pairLabel?: string | null;
  currentUnderlyingPrice?: string | number | null;
  underlyingChangePercent?: number | null;
  targetPrice?: string | number | null;
  targetLabel?: string | null;
  referenceRule?: string | null;
  points: ChartPoint[];
};

export type QuantFrontendPricePoint = {
  tokenId: string;
  marketId: number;
  marketSlug?: string | null;
  tokenSide: string;
  tsMinute?: string | null;
  timestamp: number;
  price: string | number;
};

export type QuantBlockClosePoint = {
  tokenId: string;
  marketId: number;
  marketSlug?: string | null;
  tokenSide: string;
  blockNumber: number;
  closePrice: string | number;
  closeTxHash?: string | null;
  closeLogIndex?: number | null;
  tradeCount?: number | string | null;
  volume?: string | number | null;
};

export type QuantBuildRun = {
  runId: number;
  source: string;
  mode?: string | null;
  status: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  marketsTotal?: number | string | null;
  marketsComplete?: number | string | null;
  rowsWritten?: number | string | null;
  errorCount?: number | string | null;
  lastError?: string | null;
};

export type QuantBacktestRun = {
  runId: number;
  status: string;
  marketSlug: string;
  tokenSide: string;
  priceSource: string;
  fromTs?: number | string | null;
  toTs?: number | string | null;
  fromBlock?: number | string | null;
  toBlock?: number | string | null;
  rowsProcessed?: number | string | null;
  error?: string | null;
  createdAt?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  entryThreshold?: string | number | null;
  exitThreshold?: string | number | null;
  stopLoss?: string | number | null;
  takeProfit?: string | number | null;
  maxHoldingBars?: number | string | null;
  initialCapital?: string | number | null;
  positionSize?: string | number | null;
};

export type QuantBacktestMetric = {
  runId: number;
  metricKey: string;
  metricName: string;
  metricGroup: 'overview' | 'prediction' | string;
  value?: string | number | null;
  formattedValue?: string | null;
  delta?: string | null;
  status?: 'positive' | 'negative' | 'neutral' | string | null;
  tooltip?: string | null;
  sortOrder?: number | string | null;
};

export type QuantBacktestEquityPoint = {
  runId: number;
  pointIndex: number;
  xAxis: 'timestamp' | 'block_number' | string;
  xValue: number | string;
  equity: string | number;
  drawdown: string | number;
  drawdownPct: string | number;
  cumulativeReturn: string | number;
};

export type QuantBacktestTrade = {
  runId: number;
  tradeId: string;
  marketSlug: string;
  tokenSide: 'YES' | 'NO' | string;
  side: 'LONG' | 'SHORT' | string;
  xAxis: 'timestamp' | 'block_number' | string;
  entryX: number | string;
  exitX: number | string;
  entryPrice: string | number;
  exitPrice: string | number;
  size: string | number;
  notional: string | number;
  pnl: string | number;
  pnlPct: string | number;
  holdingBars: number | string;
  exitReason: string;
};

export type QuantBacktestCreatePayload = {
  marketSlug: string;
  tokenSide: string;
  priceSource: string;
  from?: string;
  to?: string;
  fromBlock?: string;
  toBlock?: string;
  entryThreshold?: number;
  exitThreshold?: number;
  stopLoss?: number;
  takeProfit?: number;
  maxHoldingBars?: number;
  initialCapital?: number;
  positionSize?: number;
};

export type QuantListPayload<T> = {
  items: T[];
  count: number;
  source?: string;
};

export type ContentItem = {
  id?: string | number;
  contentType?: string | null;
  source?: string | null;
  category?: string | null;
  topicId?: string | null;
  title?: string | null;
  url?: string | null;
  publishedAt?: string | null;
  summary?: string | null;
  provider?: string | null;
  relevanceScore?: number | null;
  sourceCount?: number | null;
};

export type ContentPayload = {
  marketId: number;
  items: ContentItem[];
  sourceMode?: string;
  topicIds?: string[];
};

export type SystemHealth = {
  database?: string;
  redis?: boolean;
  apiStatus?: string;
  lobRuntime?: { status?: string; mode?: string };
  contentSync?: { status?: string };
  marketSync?: { updatedAt?: string | null };
  tradeSync?: { updatedAt?: string | null };
  oracleSync?: { updatedAt?: string | null };
  priceSync?: { status?: string; updatedAt?: string | null };
};

export type L2Level = {
  price?: string | number | null;
  size?: string | number | null;
};

export type LobSide = {
  bestBid?: string | number | null;
  bestAsk?: string | number | null;
  spread?: string | number | null;
  bids?: L2Level[];
  asks?: L2Level[];
};

export type LobPayload = {
  marketId: number;
  localMarketId?: number | null;
  marketTitle?: string;
  fetchedAt?: string;
  tokenMode?: boolean;
  source?: string | null;
  bookStatus?: 'ok' | 'no-book' | string | null;
  fallbackReason?: string | null;
  yes?: LobSide;
  no?: LobSide;
};

export type WorkspaceIdentity = {
  localMarketId?: number | null;
  marketId?: number | null;
  gammaMarketId?: string | number | null;
  eventId?: string | number | null;
  eventSlug?: string | null;
  selectedOutcomeKey?: string | null;
  slug?: string | null;
  conditionId?: string | null;
  questionId?: string | null;
  oracle?: string | null;
  yesTokenId?: string | null;
  noTokenId?: string | null;
};

export type WorkspaceDiagnostics = {
  marketId?: number | null;
  identityStatus?: 'ok' | 'partial' | string;
  chartStatus?: 'ok' | 'short' | 'flat' | 'snapshot' | 'missing' | string;
  oracleStatus?: string | null;
  oracleEventCount?: number;
  tradeCount?: number;
  hasPrice?: boolean;
  hasLobTokens?: boolean;
  issues?: string[];
  level?: 'ok' | 'warn' | 'critical' | string;
};

export type MarketWorkspaceHealth = {
  marketId?: number | null;
  priceStatus?: 'ok' | 'missing' | 'stale' | string;
  chartStatus?: 'ok' | 'short' | 'flat' | 'snapshot' | 'missing' | 'missing-local-history' | string;
  oracleStatus?: 'bound' | 'open-no-events' | 'unbound' | 'mismatch' | string;
  lobStatus?: 'ok' | 'no-book' | 'missing' | 'not-loaded' | string;
  servingStatus?: 'ok' | 'partial' | 'missing' | 'fallback' | string;
  groupStatus?: 'ok' | 'single-market' | 'outcome-missing' | string;
  issues?: string[];
  level?: 'ok' | 'warn' | 'critical' | string;
};

export type WorkspaceBundle = {
  market: MarketSummary | null;
  identity?: WorkspaceIdentity | null;
  diagnostics?: WorkspaceDiagnostics | null;
  health?: MarketWorkspaceHealth | null;
  group?: MarketGroupDetail | null;
  selectedOutcome?: MarketGroupOutcome | null;
  trades: TradeRow[];
  oracle: OraclePayload | null;
  price: PriceSummary | null;
  chart: ChartPayload | null;
  content: ContentPayload | null;
  lob: LobPayload | null;
};

export type MarketAiInsightFocus = {
  label: string;
  title: string;
  summary: string;
  severity: 'positive' | 'warning' | 'critical' | 'neutral' | string;
  evidence?: string | null;
};

export type MarketAiInsightPayload = {
  market?: MarketSummary | MarketListItem | null;
  selectedGroup?: MarketGroupItem | MarketGroupDetail | null;
  selectedOutcome?: MarketGroupOutcome | null;
  price?: PriceSummary | null;
  lob?: LobPayload | null;
  trades?: TradeRow[];
  oracle?: OraclePayload | null;
  content?: ContentItem[];
};

export type MarketAiInsightResponse = {
  status: 'live' | 'fallback' | 'missing-api-key' | 'agent-error' | 'invalid-payload' | string;
  generatedAt?: string;
  model?: string;
  cacheStatus?: 'hit' | 'warming' | 'warming-in-progress' | string;
  cacheKey?: string;
  brief: string;
  focus: MarketAiInsightFocus[];
  evidence?: string[];
  searchResults?: Array<{
    title?: string;
    url?: string;
    content?: string;
  }>;
  error?: string;
};

export type MarketWideAiInsightLens = 'overview' | 'special' | 'trend';

export type MarketWideSpecialMarket = {
  title: string;
  why: string;
  trend?: string | null;
  severity?: string | null;
  evidence?: string | null;
};

export type MarketWideTheme = {
  label: string;
  title: string;
  summary: string;
  severity?: string | null;
  evidence?: string | null;
};

export type MarketWideWatchItem = {
  title: string;
  reason: string;
  horizon?: string | null;
  severity?: string | null;
};

export type MarketWideAiInsightPayload = {
  lens: MarketWideAiInsightLens;
  markets: MarketListItem[];
  marketGroups: MarketGroupItem[];
  trades: TradeRow[];
  oracle: OracleEvent[];
  content: ContentItem[];
  alphaSignals?: RuntimeTradeSignal[];
  whaleSignals?: RuntimeTradeSignal[];
  suspiciousSignals?: RuntimeTradeSignal[];
};

export type MarketWideAiInsightResponse = MarketAiInsightResponse & {
  lens?: MarketWideAiInsightLens | string;
  specialMarkets?: MarketWideSpecialMarket[];
  themes?: MarketWideTheme[];
  watchlist?: MarketWideWatchItem[];
  metrics?: Record<string, string | number | boolean | string[] | null>;
  viaGateway?: boolean;
  servedBy?: string;
  gatewayFallback?: boolean;
  source?: string;
  snapshotGeneratedAt?: string;
  snapshotExpiresAt?: string;
  snapshotLiveAttempted?: boolean;
  dailyBudget?: {
    enabled?: boolean;
    limit?: number | null;
    used?: number | null;
    remaining?: number | null;
    kind?: string;
  };
};

export type SparkPoint = {
  timestamp: string;
  value: number;
};

export type RuntimeMarketTicker = {
  id: string;
  label: string;
  symbol: string;
  price?: number | null;
  changePercent?: number | null;
  currency?: string | null;
  marketCap?: number | null;
  volume24h?: number | null;
  points: SparkPoint[];
};

export type RuntimeMarketGroup = {
  kind: string;
  items: RuntimeMarketTicker[];
  generatedAt?: string;
};

export type RuntimeCommodityTapeItem = {
  id: string;
  label: string;
  symbol: string;
  price?: number | null;
  changePct?: number | null;
  changeLabel?: string | null;
  tone?: 'up' | 'down' | 'neutral' | string;
};

export type RuntimeEquityExposure = {
  ticker: string;
  name: string;
  market?: string | null;
  role?: 'producer' | 'processor' | 'consumer' | 'spread' | string;
  direction?: 'positive' | 'negative' | 'spread' | 'weak' | string;
  score?: number | null;
  impactLabel?: string | null;
  confidence?: 'high' | 'medium' | 'low' | string;
  basis?: string | null;
};

export type RuntimeLinkedMarket = {
  id?: number | string | null;
  title?: string | null;
  slug?: string | null;
  query?: string | null;
  source?: string | null;
};

export type RuntimeTransmissionChain = {
  id: string;
  commodityId: string;
  chainLabel: string;
  shockLabel?: string | null;
  shockPct?: number | null;
  tone?: 'up' | 'down' | 'watch' | 'neutral' | string;
  demandRegime?: string | null;
  lagLabel?: string | null;
  confidence?: 'high' | 'medium' | 'low' | string;
  formula?: string | null;
  winners?: RuntimeEquityExposure[];
  losers?: RuntimeEquityExposure[];
  spreadWatch?: RuntimeEquityExposure[];
  linkedMarkets?: RuntimeLinkedMarket[];
};

export type RuntimeCommodityTransmissionPayload = {
  generatedAt?: string;
  panelId?: string | null;
  source?: string | null;
  cacheMode?: string | null;
  status?: 'ok' | 'partial' | 'model' | string | null;
  sources?: Record<string, string>;
  summary?: {
    signal?: string | null;
    signalLabel?: string | null;
    bias?: 'beneficiary' | 'pressure' | 'mixed' | 'model' | string | null;
    chainCount?: number | string | null;
    liveCommodityCount?: number | string | null;
    topShockLabel?: string | null;
    topShockChangeLabel?: string | null;
    positiveCount?: number | string | null;
    negativeCount?: number | string | null;
    spreadCount?: number | string | null;
  } | null;
  commodities?: RuntimeCommodityTapeItem[];
  transmissions?: RuntimeTransmissionChain[];
};

export type RuntimeF1PanelCard = {
  id?: string;
  kind?: 'meeting' | 'session' | 'result' | 'news' | string;
  status?: 'live' | 'upcoming' | 'completed' | string;
  topic?: string | null;
  phase?: string | null;
  detail?: string | null;
  title?: string | null;
  summary?: string | null;
  primaryMetric?: string | null;
  secondaryMetric?: string | null;
  tertiaryMetric?: string | null;
  quaternaryMetric?: string | null;
  accentColor?: string | null;
  url?: string | null;
  source?: string | null;
  publishedAt?: string | null;
};

export type RuntimeF1Meeting = {
  meetingKey?: number | null;
  meetingName?: string | null;
  officialName?: string | null;
  location?: string | null;
  countryName?: string | null;
  circuitName?: string | null;
  startAt?: string | null;
  endAt?: string | null;
  status?: string | null;
};

export type RuntimeF1Payload = {
  generatedAt?: string;
  season?: number;
  source?: string | null;
  sourceUrl?: string | null;
  status?: string | null;
  focusMeeting?: RuntimeF1Meeting | null;
  cards: RuntimeF1PanelCard[];
};

export type RuntimeJin10Item = {
  id: string;
  timestamp?: string | null;
  headline?: string | null;
  summary?: string | null;
  source?: string | null;
  url?: string | null;
  important?: boolean;
  locked?: boolean;
  vipLevel?: number | string | null;
  assetHints?: string[];
  channelIds?: number[];
};

export type RuntimeJin10Payload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  status?: string | null;
  items: RuntimeJin10Item[];
};

export type RuntimeCryptoFundingItem = {
  id: string;
  exchange?: string | null;
  symbol?: string | null;
  asset?: string | null;
  pair?: string | null;
  fundingRate?: number | null;
  fundingRatePercent?: number | null;
  annualizedPercent?: number | null;
  severity?: string | null;
  tone?: 'critical' | 'warning' | 'normal' | 'neutral' | string | null;
  abnormalScore?: number | null;
  direction?: 'positive' | 'negative' | 'flat' | string | null;
  marketState?: 'longs-pay-shorts' | 'shorts-pay-longs' | 'flat' | string | null;
  heatBand?: 'extreme' | 'strong' | 'medium' | 'light' | 'flat' | string | null;
  markPrice?: number | null;
  indexPrice?: number | null;
  nextFundingTime?: string | null;
  updatedAt?: string | null;
};

export type RuntimeCryptoFundingAsset = {
  id: string;
  asset?: string | null;
  symbol?: string | null;
  venues?: number | null;
  bias?: 'longs-pay' | 'shorts-pay' | 'mixed' | 'flat' | string | null;
  consensusFundingPercent?: number | null;
  spreadPercent?: number | null;
  maxAbsFundingPercent?: number | null;
  tone?: 'critical' | 'warning' | 'normal' | 'neutral' | string | null;
  nextFundingTime?: string | null;
  quotes: RuntimeCryptoFundingItem[];
};

export type RuntimeCryptoFundingPayload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  status?: string | null;
  sources?: Record<string, string>;
  venues?: string[];
  legend?: Record<string, string>;
  assets?: RuntimeCryptoFundingAsset[];
  items: RuntimeCryptoFundingItem[];
};

export type RuntimeNbaGame = {
  id?: string;
  name?: string;
  status?: string;
  state?: string;
  tipoff?: string;
  homeTeam?: string;
  awayTeam?: string;
  homeScore?: string | number | null;
  awayScore?: string | number | null;
  broadcast?: string | null;
};

export type RuntimeNbaPayload = {
  items: RuntimeNbaGame[];
  generatedAt?: string;
};

export type RuntimeNbaIntelItem = {
  headline?: string;
  description?: string | null;
  publishedAt?: string | null;
  url?: string | null;
  source?: string | null;
  type?: string | null;
};

export type RuntimeNbaLineupPlayer = {
  side?: string;
  playerName?: string;
  position?: string;
  lineupStatus?: string;
  timestamp?: string | null;
};

export type RuntimeNbaLineupGame = {
  gameId?: string | number | null;
  label?: string;
  status?: string | null;
  starters: RuntimeNbaLineupPlayer[];
};

export type RuntimeNbaIntelPayload = {
  items: RuntimeNbaIntelItem[];
  lineups: RuntimeNbaLineupGame[];
  generatedAt?: string;
};

export type RuntimeNbaMatchupPredictorItem = {
  eventId?: string;
  name?: string | null;
  shortName?: string | null;
  tipoff?: string | null;
  state?: string | null;
  status?: string | null;
  awayTeam?: string | null;
  homeTeam?: string | null;
  awayWinProbability?: number | null;
  homeWinProbability?: number | null;
  matchupQuality?: number | null;
  projectedMargin?: number | null;
  awayExpectedPoints?: number | null;
  homeExpectedPoints?: number | null;
  lastModified?: string | null;
};

export type RuntimeNbaMatchupPredictorPayload = {
  items: RuntimeNbaMatchupPredictorItem[];
  generatedAt?: string;
  source?: string;
};

export type RuntimeGridEsportsTeamMetric = {
  won?: boolean;
  score?: number | string | null;
  kills?: number | string | null;
  deaths?: number | string | null;
};

export type RuntimeGridEsportsPmContext = {
  status?: string | null;
  marketId?: string | number | null;
  title?: string | null;
  probability?: number | string | null;
  delta?: number | string | null;
  signal?: string | null;
  matchQuality?: string | null;
};

export type RuntimeGridEsportsItem = {
  id: string;
  gameTitle?: string | null;
  tournament?: string | null;
  series?: string | null;
  teamA?: string | null;
  teamB?: string | null;
  format?: string | null;
  startTime?: string | null;
  startedAt?: string | null;
  state?: 'live' | 'upcoming' | 'finished' | 'pending-state' | 'scheduled' | string | null;
  score?: string | null;
  currentMap?: string | null;
  liveContext?: string | null;
  momentum?: number | string | null;
  contextTags?: string[];
  teamMetrics?: RuntimeGridEsportsTeamMetric[];
  pm?: RuntimeGridEsportsPmContext | null;
};

export type RuntimeGridEsportsPayload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  status?: string | null;
  cacheMode?: string | null;
  sources?: Record<string, string>;
  window?: {
    gte?: string | null;
    lte?: string | null;
  } | null;
  summary?: {
    totalSeries?: number | string | null;
    visibleSeries?: number | string | null;
    liveSeries?: number | string | null;
    officialSnapshots?: number | string | null;
    pmLinked?: number | string | null;
  } | null;
  items: RuntimeGridEsportsItem[];
};

export type RuntimeSportsOddsQuote = {
  name?: string | null;
  bestPrice?: number | string | null;
  consensusProbability?: number | string | null;
  dispersion?: number | string | null;
  bookCount?: number | string | null;
};

export type RuntimeSportsOddsItem = {
  id: string;
  sportKey?: string | null;
  sportTitle?: string | null;
  commenceTime?: string | null;
  homeTeam?: string | null;
  awayTeam?: string | null;
  event?: string | null;
  marketType?: string | null;
  bookmakerCount?: number | string | null;
  bestPrice?: number | string | null;
  consensusProbability?: number | string | null;
  dispersion?: number | string | null;
  signal?: string | null;
  lastUpdate?: string | null;
  quotes?: RuntimeSportsOddsQuote[];
  pm?: RuntimeGridEsportsPmContext | null;
};

export type RuntimeSportsOddsPayload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  status?: string | null;
  cacheMode?: string | null;
  sources?: Record<string, string>;
  summary?: {
    eventCount?: number | string | null;
    bookmakerCount?: number | string | null;
    pmLinked?: number | string | null;
    wideCount?: number | string | null;
  } | null;
  items: RuntimeSportsOddsItem[];
};

export type RuntimeInflationNowcastRow = {
  [key: string]: string | undefined;
};

export type RuntimeInflationNowcastPayload = {
  monthOverMonth?: RuntimeInflationNowcastRow | null;
  yearOverYear?: RuntimeInflationNowcastRow | null;
  quarterly?: RuntimeInflationNowcastRow[];
  generatedAt?: string;
  source?: string;
  url?: string;
  status?: string | null;
  cacheMode?: string | null;
};

export type RuntimeGeoSanctionsShockSummary = {
  hotspotCount?: number;
  newSanctionsCount?: number;
  targetLabels?: string[];
  targetSummary?: string;
  nuclearRisk?: string;
  militaryFeed?: string;
};

export type RuntimeGeoSanctionsShockItem = {
  id?: string | null;
  kind?: string | null;
  headline?: string | null;
  summary?: string | null;
  source?: string | null;
  sourceUrl?: string | null;
  occurredAt?: string | null;
  severity?: string | null;
  targetLabels?: string[];
  country?: string | null;
  tags?: string[];
  sideA?: string | null;
  sideB?: string | null;
  locationLabel?: string | null;
  latitude?: number | string | null;
  longitude?: number | string | null;
  violenceType?: string | number | null;
  deathsBest?: number | null;
  deathsLow?: number | null;
  deathsHigh?: number | null;
};

export type RuntimeGeoSanctionsShockTargetBreakdown = {
  label?: string | null;
  count?: number | null;
  latestHeadline?: string | null;
  latestOccurredAt?: string | null;
  latestSource?: string | null;
};

export type RuntimeGeoSanctionsShockLinkedMarket = {
  marketId?: number | string | null;
  slug?: string | null;
  title?: string | null;
  matchedBy?: string | null;
  score?: number | null;
  gammaActive?: boolean;
};

export type RuntimeGeoSanctionsShockPayload = {
  generatedAt?: string;
  source?: string;
  sourceUrl?: string;
  cacheMode?: string | null;
  status?: string | null;
  sources?: Record<string, string>;
  conflictProvider?: string | null;
  conflictState?: string | null;
  summary?: RuntimeGeoSanctionsShockSummary | null;
  items?: RuntimeGeoSanctionsShockItem[];
  targetBreakdown?: RuntimeGeoSanctionsShockTargetBreakdown[];
  linkedMarkets?: RuntimeGeoSanctionsShockLinkedMarket[];
  ofacRecordCountTotal?: number;
  publishDates?: string[];
};

export type RuntimePolymarketMacroMapOutcome = {
  outcomeKey?: string | null;
  gammaMarketId?: string | number | null;
  label?: string | null;
  title?: string | null;
  yesPrice?: number | string | null;
  noPrice?: number | string | null;
  volume24h?: number | string | null;
  conditionId?: string | null;
  slug?: string | null;
};

export type RuntimePolymarketMacroMapItem = {
  eventId?: string | number | null;
  slug?: string | null;
  title?: string | null;
  categoryIds?: string[];
  categoryLabels?: string[];
  marketTypes?: string[];
  endDate?: string | null;
  createdAt?: string | null;
  volume24h?: number | string | null;
  liquidity?: number | string | null;
  outcomeCount?: number | null;
  topOutcomes?: RuntimePolymarketMacroMapOutcome[];
};

export type RuntimePolymarketMacroMapCategory = {
  id?: string | null;
  label?: string | null;
  marketType?: string | null;
  activeCount?: number | null;
  topTitle?: string | null;
  volume24h?: number | string | null;
};

export type RuntimePolymarketMacroMapSummary = {
  activeCount?: number | null;
  categoryCount?: number | null;
  topCategory?: string | null;
  signal?: string | null;
  topCatalyst?: {
    title?: string | null;
    eventId?: string | number | null;
    slug?: string | null;
    endDate?: string | null;
    categoryLabels?: string[];
  } | null;
};

export type RuntimePolymarketMacroMapPayload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  cacheMode?: string | null;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: RuntimePolymarketMacroMapSummary | null;
  categories?: RuntimePolymarketMacroMapCategory[];
  items?: RuntimePolymarketMacroMapItem[];
};

export type RuntimeCpiCalendarItem = {
  id?: string | null;
  kind?: 'cpi' | 'pce' | 'nfp' | 'fomc' | string;
  title?: string | null;
  referencePeriod?: string | null;
  releaseAt?: string | null;
  releaseTimeEt?: string | null;
  source?: string | null;
  sourceUrl?: string | null;
  marketRelevance?: string | null;
};

export type RuntimeCpiCalendarBaseline = {
  status?: string | null;
  label?: string | null;
  probability?: number | string | null;
  marketTitle?: string | null;
  marketSlug?: string | null;
  source?: string | null;
};

export type RuntimeCpiCalendarSummary = {
  nextEvent?: RuntimeCpiCalendarItem | null;
  nextCpi?: RuntimeCpiCalendarItem | null;
  nextPce?: RuntimeCpiCalendarItem | null;
  nextNfp?: RuntimeCpiCalendarItem | null;
  nextFomc?: RuntimeCpiCalendarItem | null;
  signal?: string | null;
  risk?: string | null;
  hoursToEvent?: number | string | null;
  baselineLabel?: string | null;
  baselineProbability?: number | string | null;
  consensusStatus?: string | null;
};

export type RuntimeCpiReleaseCalendarPayload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  cacheMode?: string | null;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: RuntimeCpiCalendarSummary | null;
  baseline?: RuntimeCpiCalendarBaseline | null;
  consensus?: RuntimeCpiCalendarBaseline | null;
  items?: RuntimeCpiCalendarItem[];
};

export type RuntimeEnergyShockItem = {
  key?: string | null;
  label?: string | null;
  unit?: string | null;
  cadence?: string | null;
  date?: string | null;
  value?: number | string | null;
  change1?: number | string | null;
  changeWeek?: number | string | null;
  source?: string | null;
  sourceUrl?: string | null;
};

export type RuntimeEnergyShockSummary = {
  signal?: string | null;
  bias?: string | null;
  headlineImpulsePp?: number | string | null;
  linkedMarkets?: string[];
};

export type RuntimeEnergyGasolineShockPayload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  cacheMode?: string | null;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: RuntimeEnergyShockSummary | null;
  items?: RuntimeEnergyShockItem[];
};

export type RuntimeWeatherQuoteBin = {
  label?: string | null;
  bucketType?: string | null;
  minTemp?: number | string | null;
  maxTemp?: number | string | null;
  minValue?: number | string | null;
  maxValue?: number | string | null;
  unit?: string | null;
  metricType?: string | null;
  marketFamily?: string | null;
  bestBidYes?: number | string | null;
  bestAskYes?: number | string | null;
  midPriceYes?: number | string | null;
  marketId?: number | string | null;
  marketSlug?: string | null;
  marketStatus?: string | null;
  priceSource?: string | null;
  bookStatus?: string | null;
  yesTokenId?: string | null;
};

export type RuntimeGlobalWeatherCity = {
  cityId?: string | null;
  city?: string | null;
  country?: string | null;
  region?: string | null;
  lat?: number | string | null;
  lon?: number | string | null;
  timezone?: string | null;
  unit?: string | null;
  icao?: string | null;
  labelDx?: number | string | null;
  labelDy?: number | string | null;
  condition?: string | null;
  currentTemp?: number | string | null;
  todayHigh?: number | string | null;
  todayLow?: number | string | null;
  forecastHigh?: number | string | null;
  metarTemp?: number | string | null;
  hourly?: Array<{ time?: string | null; temp?: number | string | null }>;
  daily?: Array<{ date?: string | null; high?: number | string | null; low?: number | string | null }>;
  eventSlug?: string | null;
  eventTitle?: string | null;
  marketSource?: string | null;
  eventStatus?: string | null;
  marketFamily?: string | null;
  marketFamilyLabel?: string | null;
  metricType?: string | null;
  marketUrl?: string | null;
  quoteCoverage?: string | null;
  topBin?: RuntimeWeatherQuoteBin | null;
  bins?: RuntimeWeatherQuoteBin[];
  markets?: Array<{
    eventSlug?: string | null;
    eventTitle?: string | null;
    marketSource?: string | null;
    eventStatus?: string | null;
    marketFamily?: string | null;
    marketFamilyLabel?: string | null;
    metricType?: string | null;
    marketUrl?: string | null;
    quoteCoverage?: string | null;
    topBin?: RuntimeWeatherQuoteBin | null;
    bins?: RuntimeWeatherQuoteBin[];
    updatedAt?: string | null;
  }>;
  marketFamilies?: string[];
  sourceStates?: Record<string, string>;
  weatherCarryForward?: boolean;
  weatherCarryForwardFields?: string[];
  updatedAt?: string | null;
};

export type RuntimeGlobalWeatherMapPayload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  cacheMode?: string | null;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: {
    cityCount?: number | string | null;
    mappedCount?: number | string | null;
    liveMarketCount?: number | string | null;
    staleCount?: number | string | null;
    hottestCity?: RuntimeGlobalWeatherCity | null;
    marketFamilyCounts?: Record<string, number | string>;
    unmappedMarketCount?: number | string | null;
  } | null;
  items?: RuntimeGlobalWeatherCity[];
  unmappedMarkets?: Array<Record<string, unknown>>;
};

export type RuntimeWeatherNewsItem = {
  id?: string | null;
  cityId?: string | null;
  city?: string | null;
  source?: string | null;
  title?: string | null;
  summary?: string | null;
  publishedAt?: string | null;
  url?: string | null;
  severity?: string | null;
  tags?: string[];
  marketFamily?: string | null;
};

export type RuntimeWeatherNewsPayload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  cacheMode?: string | null;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: {
    articleCount?: number | string | null;
    cityCount?: number | string | null;
    warningCount?: number | string | null;
    topCity?: string | null;
  } | null;
  items?: RuntimeWeatherNewsItem[];
};

export type RuntimeFoodBasketItem = {
  key?: string | null;
  seriesId?: string | null;
  label?: string | null;
  date?: string | null;
  value?: number | string | null;
  momPct?: number | string | null;
  yoyPct?: number | string | null;
  threeMonthPct?: number | string | null;
  source?: string | null;
  sourceUrl?: string | null;
};

export type RuntimeFoodBasketSummary = {
  signal?: string | null;
  bias?: string | null;
  pressureScore?: number | string | null;
  topMover?: RuntimeFoodBasketItem | null;
  coverage?: number | string | null;
};

export type RuntimeFoodRetailBasketPayload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  cacheMode?: string | null;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: RuntimeFoodBasketSummary | null;
  items?: RuntimeFoodBasketItem[];
};

export type RuntimeMacroDriverItem = {
  key?: string | null;
  seriesId?: string | null;
  label?: string | null;
  group?: string | null;
  icon?: string | null;
  metric?: string | null;
  unit?: string | null;
  date?: string | null;
  value?: number | string | null;
  change?: number | string | null;
  changePct?: number | string | null;
  yoyPct?: number | string | null;
  tone?: string | null;
  source?: string | null;
  sourceUrl?: string | null;
};

export type RuntimeMacroDriverSummary = {
  signal?: string | null;
  bias?: string | null;
  hotCount?: number | string | null;
  coolCount?: number | string | null;
  watchCount?: number | string | null;
  coverage?: number | string | null;
  sourceCount?: number | string | null;
  topMover?: RuntimeMacroDriverItem | null;
  linkedMarketCategories?: string[];
  panelId?: string | null;
};

export type RuntimeMacroDriverPayload = {
  generatedAt?: string;
  source?: string | null;
  sourceUrl?: string | null;
  cacheMode?: string | null;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: RuntimeMacroDriverSummary | null;
  items?: RuntimeMacroDriverItem[];
};

export type RuntimeMacroRegistryItem = {
  key?: string | null;
  type?: string | null;
  group?: string | null;
  label?: string | null;
  value?: number | string | null;
  unit?: string | null;
  valueLabel?: string | null;
  change?: number | string | null;
  changeLabel?: string | null;
  date?: string | null;
  tone?: string | null;
  source?: string | null;
  sourceUrl?: string | null;
  sourceLabel?: string | null;
  domainTag?: string | null;
  severityLabel?: string | null;
  ageLabel?: string | null;
  rank?: number | string | null;
  implication?: string | null;
};

export type RuntimeMacroRegistrySummary = {
  panelId?: string | null;
  signal?: string | null;
  signalLabel?: string | null;
  bias?: string | null;
  hotCount?: number | string | null;
  coolCount?: number | string | null;
  watchCount?: number | string | null;
  rowCount?: number | string | null;
  coverage?: number | string | null;
  sourceCount?: number | string | null;
  topMover?: RuntimeMacroRegistryItem | null;
  topLabel?: string | null;
  topValueLabel?: string | null;
  topChangeLabel?: string | null;
  sourceLabel?: string | null;
};

export type RuntimeMacroRegistryPayload = {
  generatedAt?: string;
  panelId?: string | null;
  source?: string | null;
  sourceUrl?: string | null;
  cacheMode?: string | null;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: RuntimeMacroRegistrySummary | null;
  items?: RuntimeMacroRegistryItem[];
};

export type RuntimeTradeSignal = {
  marketId?: number | null;
  marketTitle?: string | null;
  timestamp?: string | null;
  txHash?: string | null;
  eventTime?: string | null;
  eventStatus?: string | null;
  side?: string | null;
  outcome?: string | null;
  price?: string | null;
  size?: string | null;
  notional?: string | null;
  severity?: string | null;
  title?: string | null;
  summary?: string | null;
  kind?: string | null;
  bias?: string | null;
  sourceLabel?: string | null;
  sourceTag?: string | null;
  headline?: string | null;
  action?: RuntimeSignalAction | null;
  contributors?: string[];
  addresses?: RuntimeSignalAddress[];
  relatedContent?: RuntimeSignalContent[];
  metrics?: RuntimeSignalMetrics | null;
};

export type RuntimeSignalAction = {
  label?: string | null;
  outcome?: string | null;
};

export type RuntimeSignalAddress = {
  address?: string | null;
  shortAddress?: string | null;
  labels?: string[];
  tradeCount?: number | string | null;
  volumeNotional?: string | null;
  marketTradeCount?: number | string | null;
  marketVolumeNotional?: string | null;
  firstTradeAt?: string | null;
  firstMarketTradeAt?: string | null;
  isNewAddress?: boolean;
  isNewToMarket?: boolean;
};

export type RuntimeSignalContent = {
  source?: string | null;
  title?: string | null;
  url?: string | null;
  publishedAt?: string | null;
  summary?: string | null;
};

export type RuntimeSignalMetrics = {
  totalNotional?: string | null;
  avgPrice?: string | null;
  currentProbability?: string | null;
  accountCount?: number | string | null;
  newAccountCount?: number | string | null;
  newToMarketCount?: number | string | null;
  tradeCount?: number | string | null;
  score?: string | null;
};

export type RuntimeSignalPayload = {
  items: RuntimeTradeSignal[];
  generatedAt?: string;
};

export type RuntimePolybeatsWallet = RuntimeSignalAddress & {
  netCashPnlProxy?: string | null;
  tradeCashPnl?: string | null;
  redeemCashflow?: string | null;
  pnlSource?: string | null;
  smartScore?: string | null;
  activeMarkets?: number | string | null;
};

export type RuntimePolybeatsItem = RuntimeTradeSignal & {
  id?: string | null;
  domain?: string | null;
  marketSlug?: string | null;
  marketCategory?: string | null;
  tags?: string[];
  wallets?: RuntimePolybeatsWallet[];
  explanation?: string | null;
  narrativeSource?: string | null;
};

export type RuntimePolybeatsPayload = {
  items: RuntimePolybeatsItem[];
  generatedAt?: string;
  status?: string | null;
  cacheMode?: string | null;
  source?: string | null;
  sources?: Record<string, string | null | undefined>;
};

export type RuntimeNewMarketSignalItem = {
  marketId?: number | null;
  title?: string | null;
  initialYesProbability?: string | number | null;
  probabilitySource?: string | null;
  observedAt?: string | null;
  marketCreatedAt?: string | null;
};

export type RuntimeNewMarketSignalsPayload = {
  items: RuntimeNewMarketSignalItem[];
  generatedAt?: string;
  status?: string | null;
};

export type RuntimeDefiTokenRow = {
  id?: string | null;
  symbol?: string | null;
  name?: string | null;
  price?: number | string | null;
  change24h?: number | string | null;
  change7d?: number | string | null;
  marketCap?: number | string | null;
  volume24h?: number | string | null;
  sparkline?: number[];
  tags?: string[];
  tone?: string | null;
};

export type RuntimeDefiTokenWatchPayload = {
  generatedAt?: string;
  status?: string | null;
  cacheMode?: string | null;
  sources?: Record<string, string>;
  summary?: {
    count?: number | string | null;
    topSymbol?: string | null;
    moveCount?: number | string | null;
  } | null;
  items?: RuntimeDefiTokenRow[];
};

export type RuntimeFinanceWatchItem = {
  id?: string | null;
  label?: string | null;
  symbol?: string | null;
  title?: string | null;
  summary?: string | null;
  source?: string | null;
  url?: string | null;
  publishedAt?: string | null;
  metric?: number | string | null;
  metricLabel?: string | null;
  metricUnit?: string | null;
  secondary?: number | string | null;
  secondaryLabel?: string | null;
  change?: number | string | null;
  changeLabel?: string | null;
  tags?: string[];
  tone?: string | null;
  points?: Array<{ timestamp?: string | null; value?: number | string | null }>;
  company?: string | null;
  institution?: string | null;
  analyst?: string | null;
  rating?: string | null;
  targetPriceLabel?: string | null;
  previousTargetPriceLabel?: string | null;
  reportPageLabel?: string | null;
};

export type RuntimeFinanceWatchPayload = {
  generatedAt?: string;
  status?: string | null;
  cacheMode?: string | null;
  panelId?: string | null;
  title?: string | null;
  headline?: {
    label?: string | null;
    score?: number | string | null;
    previousScore?: number | string | null;
    delta?: number | string | null;
    regime?: string | null;
    tone?: string | null;
  } | null;
  sources?: Record<string, string>;
  summary?: Record<string, unknown>;
  items?: RuntimeFinanceWatchItem[];
};

export type RuntimeTechPanelItem = RuntimeFinanceWatchItem & {
  category?: string | null;
  rank?: number | string | null;
  marketCap?: number | string | null;
  price?: number | string | null;
};

export type RuntimeTechPanelPayload = {
  generatedAt?: string;
  status?: string | null;
  cacheMode?: string | null;
  panelId?: string | null;
  title?: string | null;
  sources?: Record<string, string>;
  summary?: Record<string, unknown>;
  items?: RuntimeTechPanelItem[];
};

export type RuntimeFinanceCoverageKey = 'quote' | 'earn' | 'sec' | 'perp' | 'etf' | 'clob' | 'oracle' | 'flow' | string;

export type RuntimeFinanceLinkedMarket = {
  marketId?: number | string | null;
  title?: string | null;
  probability?: number | string | null;
  change24h?: number | string | null;
  volume24h?: number | string | null;
  liquidity?: number | string | null;
  spread?: number | string | null;
  endDate?: string | null;
  category?: string | null;
  categoryLabel?: string | null;
  coverage?: RuntimeFinanceCoverageKey[];
  topReason?: string | null;
  gapScore?: number | string | null;
};

export type RuntimeFinanceMarketAtlasCategory = {
  id?: string | null;
  label?: string | null;
  activeCount?: number | string | null;
  volume24h?: number | string | null;
  topTitle?: string | null;
  coverage?: RuntimeFinanceCoverageKey[];
};

export type RuntimeFinanceMarketAtlasPayload = {
  generatedAt?: string;
  status?: string | null;
  cacheMode?: string | null;
  sources?: Record<string, string>;
  summary?: {
    activeCount?: number | string | null;
    categoryCount?: number | string | null;
    topCategory?: string | null;
    topDislocation?: RuntimeFinanceLinkedMarket | null;
    coverageCount?: number | string | null;
  } | null;
  categories?: RuntimeFinanceMarketAtlasCategory[];
  items?: RuntimeFinanceLinkedMarket[];
};

export type RuntimeEquityEventRow = {
  symbol?: string | null;
  company?: string | null;
  price?: number | string | null;
  change1d?: number | string | null;
  volume24h?: number | string | null;
  nextEvent?: string | null;
  nextEventAt?: string | null;
  eventType?: string | null;
  eventTone?: string | null;
  badges?: string[];
  linkedMarkets?: RuntimeFinanceLinkedMarket[];
  pmktGapScore?: number | string | null;
};

export type RuntimeEquityEventCommandPayload = {
  generatedAt?: string;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: {
    trackedCount?: number | string | null;
    catalystCount?: number | string | null;
    topSymbol?: string | null;
    signal?: string | null;
  } | null;
  items?: RuntimeEquityEventRow[];
};

export type RuntimeOnchainTradfiPerpRow = {
  symbol?: string | null;
  display?: string | null;
  assetClass?: string | null;
  markPx?: number | string | null;
  oraclePx?: number | string | null;
  spotPx?: number | string | null;
  basisBps?: number | string | null;
  funding?: number | string | null;
  openInterest?: number | string | null;
  dayNotional?: number | string | null;
  compositeScore?: number | string | null;
  alerts?: string[];
  linkedMarkets?: RuntimeFinanceLinkedMarket[];
};

export type RuntimeOnchainTradfiPerpRadarPayload = {
  generatedAt?: string;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: {
    assetCount?: number | string | null;
    alertCount?: number | string | null;
    topSymbol?: string | null;
    signal?: string | null;
  } | null;
  items?: RuntimeOnchainTradfiPerpRow[];
};

export type RuntimeFinanceLiquidityComponent = {
  key?: string | null;
  label?: string | null;
  value?: number | string | null;
  tone?: string | null;
  detail?: string | null;
};

export type RuntimeFinanceLiquidityRow = {
  id?: string | null;
  label?: string | null;
  source?: string | null;
  signal?: string | null;
  value?: number | string | null;
  tone?: string | null;
  linkedMarket?: RuntimeFinanceLinkedMarket | null;
};

export type RuntimeFinanceLiquidityRegimePayload = {
  generatedAt?: string;
  status?: string | null;
  sources?: Record<string, string>;
  summary?: {
    regimeLabel?: string | null;
    regimeScore?: number | string | null;
    alertCount?: number | string | null;
    signal?: string | null;
  } | null;
  components?: RuntimeFinanceLiquidityComponent[];
  items?: RuntimeFinanceLiquidityRow[];
};

export type PanelDefinition = {
  id: string;
  title: string;
  eyebrow: string;
  description: string;
  size?: 'default' | 'wide' | 'tall';
};

export type PanelRenderContext = {
  bootstrap: BootstrapPayload | null;
  markets: MarketListItem[];
  marketGroups: MarketGroupItem[];
  marketGroupSort: MarketGroupSort;
  setMarketGroupSort: (sort: MarketGroupSort) => void;
  selectedMarketId: number | null;
  setSelectedMarketId: (marketId: number | null) => void;
  focusMarketGroup: (group: MarketGroupItem, outcomeKey?: string | null, marketId?: number | null) => void;
  selectedMarketGroupId: string | null;
  selectedMarketGroup: MarketGroupItem | null;
  selectedMarketGroupOutcomeKey: string | null;
  setSelectedMarketGroupOutcomeKey: (outcomeKey: string | null) => void;
  selectedMarketGroupDetail: MarketGroupDetail | null;
  selectedMarketGroupChart: MarketGroupChartPayload | null;
  selectedMarketGroupChartRange: MarketGroupChartRange;
  setSelectedMarketGroupChartRange: (range: MarketGroupChartRange) => void;
  selectedMarket: MarketSummary | null;
  selectedWeatherCityId: string | null;
  setSelectedWeatherCityId: (cityId: string | null) => void;
  bundle: WorkspaceBundle | null;
  health: SystemHealth | null;
  globalTrades: TradeRow[];
  globalOracle: OracleEvent[];
  latestContent: ContentItem[];
  runtimeData: Record<string, unknown>;
  commodities?: RuntimeMarketGroup | null;
  crypto?: RuntimeMarketGroup | null;
  f1?: RuntimeF1Payload | null;
  jin10?: RuntimeJin10Payload | null;
  nba?: RuntimeNbaPayload | null;
  nbaIntel?: RuntimeNbaIntelPayload | null;
  nbaMatchupPredictor?: RuntimeNbaMatchupPredictorPayload | null;
  inflationNowcast?: RuntimeInflationNowcastPayload | null;
  alphaSignals?: RuntimeSignalPayload | null;
  whaleTrades?: RuntimeSignalPayload | null;
  suspiciousTrades?: RuntimeSignalPayload | null;
};
