import { useContext, useEffect, useRef, useState } from 'preact/hooks';
import { PanelResourceVisibility, usePanelResource } from '@/panels/usePanelResource';
import type { LobPayload } from '@/types';
import { bookMidValue, directionFromValues, staleLob, timestampMillis, type BookSide, type RefreshDirection } from './orderBook';
import { orderBookResource } from './orderBookResource';

export function useFocusedOrderBook({ marketId, selectedTokenId, selectedNoTokenId, marketIsClosed, bookSide }: {
  marketId: number | null; selectedTokenId: string; selectedNoTokenId: string; marketIsClosed: boolean;
  bookSide: BookSide;
}) {
  const visible = useContext(PanelResourceVisibility);
  const enabled = !marketIsClosed && Boolean(marketId && selectedTokenId);
  const resource = usePanelResource(orderBookResource(marketId, selectedTokenId, selectedNoTokenId), visible && enabled);
  const selectedTokenKey = selectedTokenId ? `${marketId}:${selectedTokenId}:${selectedNoTokenId}` : '';
  const lob = !enabled ? null : resource.error ? staleLob(resource.data) : resource.data;
  const previous = useRef({ key: '', side: bookSide, lob: null as LobPayload | null,
    pulseId: 0, direction: 'flat' as RefreshDirection });
  if (previous.current.key !== selectedTokenKey || previous.current.side !== bookSide) {
    previous.current = { key: selectedTokenKey, side: bookSide, lob: null, pulseId: 0, direction: 'flat' };
  }
  if (resource.data !== previous.current.lob) {
    previous.current = { key: selectedTokenKey, side: bookSide, lob: resource.data,
      pulseId: previous.current.pulseId + 1,
      direction: directionFromValues(bookMidValue(resource.data, bookSide), bookMidValue(previous.current.lob, bookSide)) };
  }
  // Display-only clock: expire continuity and update age without a new response.
  const [, tick] = useState(0);
  useEffect(() => {
    if (!enabled || !visible) return;
    const timer = window.setInterval(() => tick(value => value + 1), 2000);
    return () => window.clearInterval(timer);
  }, [enabled, visible]);
  return { selectedTokenKey, tokenLobState: {
    key: selectedTokenKey, lob, loading: enabled && resource.loading, error: enabled ? resource.error : null,
    updatedAt: timestampMillis(lob?.yes?.receivedAt || lob?.yes?.observedAt),
    pulseId: previous.current.pulseId, direction: previous.current.direction,
  } };
}
