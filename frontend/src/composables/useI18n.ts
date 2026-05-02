import { ref } from 'vue'
import {
  t as _t,
  setLocale as _setLocale,
  type Locale,
} from '@/i18n'

const STORAGE_KEY = 'shadowfleet_locale'

function loadLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'zh' || saved === 'en') return saved
  } catch {
    // ignore
  }
  return 'zh'
}

export const locale = ref<Locale>(loadLocale())

export function setLocale(l: Locale): void {
  locale.value = l
  try { localStorage.setItem(STORAGE_KEY, l) } catch { /* ignore */ }
  _setLocale(l)
}

export const localeName = (l: Locale) => l === 'zh' ? '中文' : 'English'

export function t(key: string, params?: Record<string, string | number>): string {
  return _t(key, params)
}

export function useI18n() {
  return {
    locale,
    setLocale,
    t,
    localeName,
    availableLocales: ['en', 'zh'] as Locale[],
  }
}
