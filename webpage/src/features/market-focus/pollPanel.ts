/** One in-flight request per visible panel; failures cannot overlap retries. */
export function pollPanel<T>(load: (signal: AbortSignal) => Promise<T>, apply: (value: T) => void,
  failed: () => void, intervalMs: number, initialDelayMs = 0) {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let failures = 0;
  let retryAt = 0;
  const schedule = (delay: number) => { timer = setTimeout(run, delay); };
  const run = async () => {
    if (stopped || document.hidden || controller) return;
    if (Date.now() < retryAt) { schedule(retryAt - Date.now()); return; }
    const current = new AbortController();
    controller = current;
    let delay = intervalMs;
    try {
      const payload = await load(current.signal);
      if (!stopped && !current.signal.aborted) { apply(payload); failures = 0; }
    } catch (error) {
      if (!stopped && !current.signal.aborted) {
        failed(); failures = Math.min(4, failures + 1);
        const retryAfter = Number((error as { retryAfterMs?: number })?.retryAfterMs) || 0;
        delay = Math.max(retryAfter, Math.min(60_000, 5000 * 2 ** failures));
        retryAt = Date.now() + delay;
      }
    } finally {
      if (controller === current) controller = undefined;
      if (!stopped && !document.hidden && !current.signal.aborted) schedule(delay + Math.random() * 500);
    }
  };
  const visibility = () => {
    clearTimeout(timer);
    if (document.hidden) { controller?.abort(); controller = undefined; }
    else schedule(Math.max(250, retryAt - Date.now()));
  };
  document.addEventListener('visibilitychange', visibility);
  schedule(initialDelayMs);
  return () => {
    stopped = true; clearTimeout(timer); controller?.abort();
    document.removeEventListener('visibilitychange', visibility);
  };
}
