import { createContext, type ComponentChildren } from 'preact';
import { useContext, useMemo, useState } from 'preact/hooks';
import en from '@/locales/en.json';
import zh from '@/locales/zh.json';

export type Locale = 'en' | 'zh';
export type MessageKey = keyof typeof en;
type MessageParams = Record<string, string | number>;

const STORAGE_KEY = 'polydata:locale:v1';
const catalogs: Record<Locale, Record<MessageKey, string>> = { en, zh };

function detectLocale(): Locale {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'en' || stored === 'zh') return stored;
  } catch {
    // Storage may be blocked. Browser detection remains a safe fallback.
  }
  return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

function interpolate(message: string, params?: MessageParams) {
  if (!params) return message;
  return message.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, key: string) => {
    const value = params[key];
    return value === undefined ? match : String(value);
  });
}

type I18nValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, params?: MessageParams) => string;
  formatDateTime: (value: string | number | Date) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatPercent: (value: number, options?: Intl.NumberFormatOptions) => string;
};

const I18nContext = createContext<I18nValue | null>(null);

export function LocaleProvider({ children }: { children: ComponentChildren }) {
  const [locale, setLocaleState] = useState<Locale>(detectLocale);
  const value = useMemo<I18nValue>(() => {
    const intlLocale = locale === 'zh' ? 'zh-CN' : 'en-US';
    const setLocale = (next: Locale) => {
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // Keep the in-memory language even when persistence is unavailable.
      }
      document.documentElement.lang = next === 'zh' ? 'zh-CN' : 'en';
      setLocaleState(next);
    };
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
    return {
      locale,
      setLocale,
      t: (key, params) => interpolate(catalogs[locale][key] || catalogs.en[key] || key, params),
      formatDateTime: (input) => {
        const date = input instanceof Date ? input : new Date(input);
        return Number.isNaN(date.getTime())
          ? '—'
          : new Intl.DateTimeFormat(intlLocale, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
      },
      formatNumber: (input, options) => new Intl.NumberFormat(intlLocale, options).format(input),
      formatPercent: (input, options) => new Intl.NumberFormat(intlLocale, {
        style: 'percent',
        maximumFractionDigits: 1,
        ...options,
      }).format(input),
    };
  }, [locale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error('useI18n must be used inside LocaleProvider');
  return value;
}
