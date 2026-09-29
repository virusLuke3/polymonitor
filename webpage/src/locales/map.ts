import zh from './zh.json';

/** Map renderers share the UI catalog without importing the Preact provider. */
export function mapText(locale: 'en' | 'zh', text: string): string {
  if (locale === 'en') return text;
  const catalog = zh as Record<string, string>;
  return catalog[`map.${text.toLowerCase().replace(/[^a-z0-9]/g, '')}`] ?? text;
}
