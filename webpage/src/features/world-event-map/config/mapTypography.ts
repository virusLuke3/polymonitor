let mapFonts: Promise<void> | undefined;

/** Shared font download. Renderers paint immediately and relayout on completion. */
export function loadMapFonts(): Promise<void> {
  if (typeof document === 'undefined') return Promise.resolve();
  return mapFonts ??= (async () => {
    await import('@fontsource-variable/noto-sans-sc/wght.css');
    if (!document.fonts?.load) return;
    await Promise.allSettled([
      document.fonts.load('400 12px "Noto Sans SC Variable"', 'Tokyo São Paulo Montréal 北京 新加坡 東京'),
      document.fonts.load('500 12px "Polymonitor Map Sans Medium"', 'World'),
      document.fonts.load('400 12px "Polymonitor Map Sans Regular"', 'World'),
    ]);
  })().catch(() => undefined);
}
