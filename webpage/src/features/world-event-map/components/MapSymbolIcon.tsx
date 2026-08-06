import type { GeoEventSeverity } from '../domain/types';
import {
  MAP_SEVERITY_STYLES,
  MAP_SYMBOL_DEFINITIONS,
  MAP_SYMBOL_SIZE,
  type MapSymbolKey,
} from '../config/mapSymbols';

export function MapSymbolIcon({
  symbol,
  color = 'currentColor',
  severity,
  size = 14,
  label,
  className,
}: {
  symbol: MapSymbolKey;
  color?: string;
  severity?: GeoEventSeverity;
  size?: number;
  label?: string;
  className?: string;
}) {
  const definition = MAP_SYMBOL_DEFINITIONS[symbol];
  const severityStyle = severity ? MAP_SEVERITY_STYLES[severity] : null;
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox={`0 0 ${MAP_SYMBOL_SIZE} ${MAP_SYMBOL_SIZE}`}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : 'true'}
      focusable="false"
    >
      {severityStyle ? (
        <circle
          cx="24"
          cy="24"
          r="21"
          fill="rgba(3, 9, 13, 0.82)"
          stroke={severityStyle.color}
          strokeWidth={severityStyle.lineWidth * 1.6}
        />
      ) : null}
      <g fill={severityStyle?.color || color} fillRule="evenodd">
        {definition.paths.map((path) => <path key={path} d={path} />)}
      </g>
    </svg>
  );
}
