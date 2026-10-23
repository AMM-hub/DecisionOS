import { describe, expect, it } from 'vitest'
import {
  formatDate,
  formatDateTime,
  shortId,
  titleCase,
} from '~/composables/format'

describe('formatDate', () => {
  const iso = '2026-03-09T12:00:00'

  it('formats dates for English with an unambiguous day-first layout', () => {
    expect(formatDate(iso, 'en')).toBe('09 Mar 2026')
  })

  it('formats dates for Arabic', () => {
    const formatted = formatDate(iso, 'ar')
    expect(formatted).not.toBe(formatDate(iso, 'en'))
    expect(formatted).toMatch(/٢٠٢٦|2026/)
  })

  it('handles empty and invalid values', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate('')).toBe('—')
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })
})

describe('formatDateTime', () => {
  it('includes the date and time', () => {
    const formatted = formatDateTime('2026-03-09T14:30:00', 'en')
    expect(formatted).toContain('09 Mar 2026')
    expect(formatted).toMatch(/14:30|2:30/)
  })

  it('returns a dash for missing values', () => {
    expect(formatDateTime(undefined)).toBe('—')
  })
})

describe('shortId', () => {
  it('truncates long identifiers', () => {
    expect(shortId('abcdef1234567890')).toBe('abcdef12')
    expect(shortId('abcdef1234567890', 4)).toBe('abcd')
  })

  it('keeps short identifiers intact', () => {
    expect(shortId('abc')).toBe('abc')
    expect(shortId(null)).toBe('—')
  })
})

describe('titleCase', () => {
  it('turns enum underscores into title case words', () => {
    expect(titleCase('in_progress')).toBe('In Progress')
    expect(titleCase('grain_not_proven')).toBe('Grain Not Proven')
  })

  it('capitalises single words and handles empty values', () => {
    expect(titleCase('proposed')).toBe('Proposed')
    expect(titleCase(null)).toBe('—')
  })
})
