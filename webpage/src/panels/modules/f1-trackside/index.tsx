import type { RuntimeF1PanelCard, RuntimeF1Payload } from '@/types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { emptyState } from '@/panels/shared/renderers';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { fetchRuntimeF1 } from '@/services/api';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

function tagTone(label: string) {
  const normalized = label.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  if (['news', 'live'].includes(normalized)) return normalized;
  if (['alert', 'risk', 'delist'].includes(normalized)) return 'alert';
  if (['exchange', 'listing', 'futures'].includes(normalized)) return 'exchange';
  if (['btc', 'eth', 'crypto'].includes(normalized)) return 'crypto';
  if (['ai', 'tech'].includes(normalized)) return 'tech';
  if (['policy', 'reg'].includes(normalized)) return 'policy';
  return 'default';
}

function inferBweTags(card: RuntimeF1PanelCard) {
  const tags: string[] = [];
  tags.push(card.status === 'live' ? 'LIVE' : 'NEWS');
  const text = [
    card.title,
    card.summary,
    card.topic,
    card.phase,
    card.primaryMetric,
    card.secondaryMetric,
    card.tertiaryMetric,
  ].filter(Boolean).join(' ');
  if (/binance|upbit|bithumb|coinbase|okx|bybit|kraken|exchange|交易所|币安/i.test(text)) tags.push('EXCHANGE');
  if (/delist|下架/i.test(text)) tags.push('DELIST');
  if (/\blisting\b|\blist\b|上线|上新/i.test(text)) tags.push('LISTING');
  if (/futures|perpetual|合约|永续/i.test(text)) tags.push('FUTURES');
  if (/bitcoin|btc|比特币/i.test(text)) tags.push('BTC');
  if (/ethereum|eth|以太坊/i.test(text)) tags.push('ETH');
  if (/crypto|token|usdt|coin|代币|加密/i.test(text)) tags.push('CRYPTO');
  if (/\bai\b|人工智能|openai|nvidia|芯片|算力/i.test(text)) tags.push('AI');
  if (/risk|hack|exploit|漏洞|攻击|监管|sec|cftc|制裁/i.test(text)) tags.push('RISK');
  return tags.slice(0, 3).map((label) => ({ label, tone: tagTone(label) }));
}

function topicHints(card: RuntimeF1PanelCard) {
  const text = [card.title, card.summary].filter(Boolean).join(' ');
  const hints: string[] = [];
  [
    ['Binance', /binance|币安/i],
    ['Upbit', /upbit/i],
    ['Bithumb', /bithumb/i],
    ['BTC', /bitcoin|btc|比特币/i],
    ['ETH', /ethereum|eth|以太坊/i],
    ['USDT', /usdt/i],
    ['AI', /\bai\b|人工智能|openai|nvidia|芯片|算力/i],
    ['Futures', /futures|perpetual|合约|永续/i],
  ].forEach(([label, pattern]) => {
    if ((pattern as RegExp).test(text) && !hints.includes(label as string)) hints.push(label as string);
  });
  return hints.slice(0, 3);
}

function splitFlashText(card: RuntimeF1PanelCard) {
  const title = card.title || 'BWENews update';
  if (card.summary?.trim()) return { title, summary: card.summary.trim() };
  if (title.length < 62) return { title, summary: '' };
  const splitAt = title.search(/[:：。；;]/);
  const index = splitAt > 18 && splitAt < 72 ? splitAt + 1 : 50;
  return {
    title: `${title.slice(0, index).trim()}${index === 50 ? '...' : ''}`,
    summary: title.slice(index).trim(),
  };
}

function f1CardList(cards: RuntimeF1PanelCard[], copy: ReturnType<typeof useSpecialistCopy>['copy']) {
  if (!cards.length) return emptyState(copy('empty', 'No BWENews feed items loaded yet.'));
  return (
    <div className="wm-f1-market-list">
      {cards.map((card, index) => {
        const tags = inferBweTags(card);
        const hints = topicHints(card);
        const flashText = splitFlashText(card);
        return (
          <a
            className={`wm-f1-card is-${card.status || 'upcoming'} is-${card.kind || 'meeting'}`}
            key={card.id || `${card.title || 'card'}-${index}`}
            href={card.url || undefined}
            target={card.url ? '_blank' : undefined}
            rel={card.url ? 'noreferrer' : undefined}
            title={card.title || 'BWENews update'}
          >
            <div className="wm-f1-card-head">
              <div className="wm-f1-card-meta">
                <span className="wm-f1-card-dot" style={{ background: card.accentColor || undefined }} />
                <span>{card.source || card.topic || 'BWENews'}</span>
                <span>·</span>
                <span>{card.phase || 'flash'}</span>
                {card.detail ? (
                  <>
                    <span>·</span>
                    <span>{card.detail}</span>
                  </>
                ) : null}
              </div>
              <div className="wm-f1-card-tags" aria-label={copy('labelsAria', 'BWE labels')}>
                {tags.map((tag) => (
                  <span className={`wm-f1-tag ${tag.tone}`} key={`${card.id || index}-${tag.label}`}>{tag.label}</span>
                ))}
              </div>
            </div>
            <strong className="wm-f1-card-title">{flashText.title}</strong>
            {flashText.summary ? <div className="wm-f1-card-summary">{flashText.summary}</div> : null}
            {hints.length ? (
              <div className="wm-f1-card-topics">
                {hints.map((hint) => <span key={`${card.id || index}-${hint}`}>#{hint}</span>)}
              </div>
            ) : null}
          </a>
        );
      })}
    </div>
  );
}

function F1TracksidePanel({ cards }: { cards: RuntimeF1PanelCard[] }) {
  const { copy } = useSpecialistCopy('f1-trackside');
  return <Panel title={copy('title', 'BWE NEWS')} badge="LIVE" status="live" count={cards.length} className="wm-market-panel wm-f1-panel">{f1CardList(cards, copy)}</Panel>;
}

const renderers: PanelRenderMap = {
  'f1-trackside': {
    render: (ctx) => <F1TracksidePanel cards={(ctx.runtimeData['f1-trackside'] as RuntimeF1Payload | undefined)?.cards || []} />,
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'f1-trackside',
  title: 'BWE News',
  eyebrow: 'news',
  description: 'BWENews runtime RSS flashes with cached auto-refresh.',
  defaultEnabled: true,
}, {
  tier: 'fast',
  limit: 10,
  fetchData: (context, limit) => fetchRuntimeF1(limit, context?.signal),
});
