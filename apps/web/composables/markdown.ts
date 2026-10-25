// Minimal, dependency-free formatter for assistant answers.
//
// The AI layer answers in light markdown (bold, inline code, bullet/numbered
// lists, pipe tables, fenced code). Rendering it as raw pre-wrap text shows
// literal `**` and pipes, so we parse the small subset into typed blocks and
// let Vue render them as elements. No `v-html`, no HTML strings — model output
// can never inject markup.

export interface InlineSpan {
  text: string
  bold?: boolean
  code?: boolean
}

export type MarkdownBlock =
  | { type: 'paragraph'; spans: InlineSpan[] }
  | { type: 'list'; ordered: boolean; items: InlineSpan[][] }
  | { type: 'code'; text: string; lang: string | null }
  | { type: 'table'; head: InlineSpan[][]; rows: InlineSpan[][][] }
  | { type: 'heading'; level: number; spans: InlineSpan[] }

const FENCE = /^\s*```(.*)$/
const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/
const BULLET = /^\s*[-*+]\s+(.*)$/
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/
const HEADING = /^\s*(#{1,4})\s+(.*)$/

export function inlineSpans(text: string): InlineSpan[] {
  const spans: InlineSpan[] = []
  // Split on **bold** and `code`, keeping the delimiters so we know the kind.
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  for (const part of parts) {
    if (!part) continue
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      spans.push({ text: part.slice(2, -2), bold: true })
    } else if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      spans.push({ text: part.slice(1, -1), code: true })
    } else {
      spans.push({ text: part })
    }
  }
  return spans
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split('|').map(cell => cell.trim())
}

function isTableStart(lines: string[], index: number): boolean {
  const line = lines[index]
  const next = lines[index + 1]
  if (line === undefined || next === undefined) return false
  if (!line.includes('|')) return false
  return TABLE_DIVIDER.test(next)
}

export function parseMarkdown(source: string): MarkdownBlock[] {
  if (!source.trim()) return []
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const blocks: MarkdownBlock[] = []
  let paragraph: string[] = []

  const flushParagraph = () => {
    if (!paragraph.length) return
    const text = paragraph.join(' ').trim()
    if (text) blocks.push({ type: 'paragraph', spans: inlineSpans(text) })
    paragraph = []
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i] as string
    const fence = line.match(FENCE)
    if (fence) {
      flushParagraph()
      const lang = (fence[1] ?? '').trim() || null
      const body: string[] = []
      i += 1
      while (i < lines.length && !FENCE.test(lines[i] as string)) {
        body.push(lines[i] as string)
        i += 1
      }
      blocks.push({ type: 'code', text: body.join('\n'), lang })
      continue
    }

    if (!line.trim()) {
      flushParagraph()
      continue
    }

    const heading = line.match(HEADING)
    if (heading) {
      flushParagraph()
      blocks.push({
        type: 'heading',
        level: (heading[1] ?? '#').length,
        spans: inlineSpans((heading[2] ?? '').trim()),
      })
      continue
    }

    if (isTableStart(lines, i)) {
      flushParagraph()
      const head = splitRow(line).map(cell => inlineSpans(cell))
      const rows: InlineSpan[][][] = []
      i += 2
      while (i < lines.length) {
        const rowLine = lines[i] as string
        if (!rowLine.trim() || !rowLine.includes('|')) {
          i -= 1
          break
        }
        rows.push(splitRow(rowLine).map(cell => inlineSpans(cell)))
        i += 1
      }
      blocks.push({ type: 'table', head, rows })
      continue
    }

    const bullet = line.match(BULLET)
    const numbered = line.match(NUMBERED)
    if (bullet || numbered) {
      flushParagraph()
      const ordered = Boolean(numbered)
      const items: InlineSpan[][] = []
      while (i < lines.length) {
        const current = lines[i] as string
        const match = ordered ? current.match(NUMBERED) : current.match(BULLET)
        if (!match) break
        items.push(inlineSpans((match[1] ?? '').trim()))
        i += 1
      }
      i -= 1
      blocks.push({ type: 'list', ordered, items })
      continue
    }

    paragraph.push(line.trim())
  }

  flushParagraph()
  return blocks
}

/** Plain-text version, used where markup would be noise (titles, aria labels). */
export function markdownToText(source: string): string {
  return parseMarkdown(source)
    .map((block) => {
      const flatten = (spans: InlineSpan[]) => spans.map(span => span.text).join('')
      if (block.type === 'paragraph' || block.type === 'heading') return flatten(block.spans)
      if (block.type === 'code') return block.text
      if (block.type === 'list') return block.items.map(flatten).join(' ')
      return block.rows.map(row => row.map(flatten).join(' · ')).join(' ')
    })
    .join('\n')
}
