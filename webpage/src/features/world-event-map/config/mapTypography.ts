export async function loadMapFonts() {
  if (typeof document === 'undefined') return;
  const loading = (async () => {
    await import('@fontsource-variable/noto-sans-sc/wght.css');
    if (!document.fonts?.load) return;
    // Request representative subsets, not every Chinese glyph or page font.
    await Promise.allSettled([
      document.fonts.load('400 12px "Noto Sans SC Variable"', 'Tokyo São Paulo Montréal 北京 新加坡 東京'),
      document.fonts.load('500 12px "Polymonitor Map Sans Medium"', 'World'),
      document.fonts.load('400 12px "Polymonitor Map Sans Regular"', 'World'),
    ]);
  })().catch(() => undefined);
  // A failed/stalled font must not hold both primary and fallback renderers
  // indefinitely. CSS fallback remains usable; late fonts can still load.
  let timer: ReturnType<typeof setTimeout> | undefined;
  try { await Promise.race([loading, new Promise<void>(resolve => { timer = setTimeout(resolve, 3000); })]); }
  finally { clearTimeout(timer); }
}
