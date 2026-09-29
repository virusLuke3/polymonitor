function numericValue(value?: number | string | null) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function toneFromValue(value?: number | string | null) {
  const numeric = numericValue(value);
  if (numeric === null) return 'neutral';
  if (numeric > 0) return 'up';
  if (numeric < 0) return 'down';
  return 'neutral';
}

export function formatMoney(value?: number | string | null, digits = 2) {
  const numeric = numericValue(value);
  if (numeric === null) return '--';
  const maximumFractionDigits = Math.abs(numeric) >= 1000 ? 2 : digits;
  return `$${new Intl.NumberFormat('en-US', { maximumFractionDigits }).format(numeric)}`;
}

export function formatPercent(value?: number | string | null, digits = 2) {
  const numeric = numericValue(value);
  if (numeric === null) return '--';
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(digits)}%`;
}

export function StatusDots() {
  return (
    <div className="wm-monitor-dots" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}
