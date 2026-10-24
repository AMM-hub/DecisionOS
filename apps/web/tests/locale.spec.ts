import { describe, expect, it } from 'vitest'
import en from '~/locales/en.json'
import ar from '~/locales/ar.json'
import { t } from '~/composables/locale'

function flattenKeys(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return [prefix]
  }
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    flattenKeys(child, prefix ? `${prefix}.${key}` : key),
  )
}

describe('t', () => {
  it('resolves English common and nav keys', () => {
    expect(t('common.appName', 'en')).toBe('DecisionOS')
    expect(t('common.save', 'en')).toBe('Save')
    expect(t('nav.home', 'en')).toBe('Home')
    expect(t('nav.decisions', 'en')).toBe('Decisions')
    expect(t('nav.pilotDashboard', 'en')).toBe('Pilot Center')
  })

  it('resolves Arabic keys and differs from English', () => {
    const arabic = t('nav.decisions', 'ar')
    expect(arabic).toBe('القرارات')
    expect(arabic).not.toBe(t('nav.decisions', 'en'))
  })

  it('returns the path itself for unknown keys', () => {
    expect(t('does.not.exist', 'en')).toBe('does.not.exist')
    expect(t('does.not.exist', 'ar')).toBe('does.not.exist')
  })
})

describe('locale parity', () => {
  it('has identical key sets in English and Arabic', () => {
    const enKeys = flattenKeys(en).sort()
    const arKeys = flattenKeys(ar).sort()
    expect(arKeys).toEqual(enKeys)
  })
})
