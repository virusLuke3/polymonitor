import { useEffect, useRef } from 'preact/hooks';
import type { RuntimeGlobalWeatherCity } from '@/types';
import { num } from './model';

export function WeatherCanvasSparkline({
  values,
  className = '',
}: {
  values: number[];
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || values.length < 2) return;
    const rect = canvas.getBoundingClientRect();
    const pixelRatio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width));
    const height = Math.max(1, Math.floor(rect.height));
    canvas.width = Math.floor(width * pixelRatio);
    canvas.height = Math.floor(height * pixelRatio);
    const context = canvas.getContext('2d');
    if (!context) return;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(1, max - min);
    const xFor = (index: number) => (index / Math.max(1, values.length - 1)) * (width - 4) + 2;
    const yFor = (value: number) => height - 3 - ((value - min) / range) * (height - 6);

    context.strokeStyle = 'rgba(255,255,255,0.08)';
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(0, height - 4);
    context.lineTo(width, height - 4);
    context.moveTo(0, Math.round(height * 0.5));
    context.lineTo(width, Math.round(height * 0.5));
    context.stroke();

    context.strokeStyle = getComputedStyle(canvas).color || '#7edcff';
    context.lineWidth = 2;
    context.lineJoin = 'round';
    context.lineCap = 'round';
    context.beginPath();
    values.forEach((value, index) => {
      const x = xFor(index);
      const y = yFor(value);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();

    context.fillStyle = context.strokeStyle;
    values.forEach((value, index) => {
      const x = xFor(index);
      const y = yFor(value);
      context.beginPath();
      context.arc(x, y, 1.6, 0, Math.PI * 2);
      context.fill();
    });
  }, [values]);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}

export function WeatherMiniLine({
  city,
  className = '',
  limit = 24,
}: {
  city?: RuntimeGlobalWeatherCity | null;
  className?: string;
  limit?: number;
}) {
  const points = (city?.hourly || []).filter((point) => num(point.temp) !== null).slice(0, limit);
  if (points.length < 2) return <div className={`wm-weather-detail-empty-line ${className}`.trim()}>No hourly curve</div>;
  const values = points.map((point) => num(point.temp) || 0);
  return <WeatherCanvasSparkline values={values} className={`wm-weather-detail-line ${className}`.trim()} />;
}
