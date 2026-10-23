// Shared display formatters.
// Centralised so every screen renders dates, ids and enums the same way.
// Previously each page rolled its own toLocaleDateString(), which produced
// ambiguous MM/DD/YYYY output that flipped meaning between locales.

export function formatDate(iso: string | null | undefined, locale: string = 'en'): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-BH' : 'en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(d)
}

export function formatDateTime(iso: string | null | undefined, locale: string = 'en'): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-BH' : 'en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(d)
}

/** Short, human-readable handle for a UUID — full value stays in the tooltip. */
export function shortId(id: string | null | undefined, len = 8): string {
  if (!id) return '—'
  return id.length > len ? id.slice(0, len) : id
}

/** Initial-caps enum label: "proposed" -> "Proposed". */
export function titleCase(s: string | null | undefined): string {
  if (!s) return '—'
  return s.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** 1234 -> "1,234" with tabular-friendly grouping. */
export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(v)
}
