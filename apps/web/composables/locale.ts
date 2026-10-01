import { ref, computed } from 'vue'

export type Locale = 'en' | 'ar'

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

let messages: Record<string, any> | null = null

export async function loadMessages(locale: Locale): Promise<Record<string, any>> {
  if (messages) return messages
  try {
    const res = await fetch(`/locales/${locale}.json`)
    if (res.ok) {
      messages = await res.json()
    }
  } catch {
    // fallback to empty
  }
  // Load English as fallback always
  if (locale !== 'en') {
    try {
      const enRes = await fetch('/locales/en.json')
      if (enRes.ok) {
        const enData = await enRes.json()
        if (!messages) messages = enData
        else messages = deepMerge(enData, messages!)
      }
    } catch {
      // ignore
    }
  }
  return messages || {}
}

function deepMerge(base: any, override: any): any {
  const result = { ...base }
  for (const key of Object.keys(override)) {
    if (typeof override[key] === 'object' && override[key] !== null && !Array.isArray(override[key])) {
      result[key] = deepMerge(result[key] || {}, override[key])
    } else {
      result[key] = override[key]
    }
  }
  return result
}

export function t(path: string, locale: Locale = 'en'): string {
  if (!messages) return path
  const parts = path.split('.')
  let current: any = messages
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = current[part]
    } else {
      return path // fallback to key
    }
  }
  return typeof current === 'string' ? current : path
}

export const SUPPORTED_LOCALES: Array<{ code: Locale; label: string; native: string }> = [
  { code: 'en', label: 'English', native: 'English' },
  { code: 'ar', label: 'Arabic', native: 'العربية' },
]