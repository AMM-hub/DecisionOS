import { ref, computed } from 'vue'
import en from '~/locales/en.json'
import ar from '~/locales/ar.json'

export type Locale = 'en' | 'ar'

const bundles: Record<Locale, Record<string, any>> = { en, ar }

const currentLocale = ref<Locale>('en')

export function useLocale() {
  function setLocale(locale: Locale) {
    currentLocale.value = locale
    document.documentElement.lang = locale
    document.documentElement.dir = locale === 'ar' ? 'rtl' : 'ltr'
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('decisionos_locale', locale)
    }
  }

  // Restore saved locale
  const saved = typeof localStorage !== 'undefined' ? localStorage.getItem('decisionos_locale') : null
  if (saved === 'ar' || saved === 'en') {
    setLocale(saved)
  }

  const isRTL = computed(() => currentLocale.value === 'ar')

  return { locale: currentLocale, setLocale, isRTL }
}

function resolve(bundle: Record<string, any>, path: string): string | undefined {
  const parts = path.split('.')
  let current: any = bundle
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = current[part]
    } else {
      return undefined
    }
  }
  return typeof current === 'string' ? current : undefined
}

export function t(path: string, locale: Locale = 'en'): string {
  const value = resolve(bundles[locale], path)
  if (value !== undefined) return value
  if (locale !== 'en') {
    const fallback = resolve(bundles.en, path)
    if (fallback !== undefined) return fallback
  }
  return path
}

export const SUPPORTED_LOCALES: Array<{ code: Locale; label: string; native: string }> = [
  { code: 'en', label: 'English', native: 'English' },
  { code: 'ar', label: 'Arabic', native: 'العربية' },
]
