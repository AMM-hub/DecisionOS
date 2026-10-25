import { describe, expect, it } from 'vitest'
import { inlineSpans, markdownToText, parseMarkdown } from '~/composables/markdown'

describe('markdown formatter', () => {
  it('splits bold and inline code without leaking the delimiters', () => {
    const spans = inlineSpans('Total is **420** in `tickets_cases.csv` ok')
    expect(spans).toEqual([
      { text: 'Total is ' },
      { text: '420', bold: true },
      { text: ' in ' },
      { text: 'tickets_cases.csv', code: true },
      { text: ' ok' },
    ])
  })

  it('parses a pipe table with a divider row', () => {
    const blocks = parseMarkdown('| Priority | Tickets |\n|---|---|\n| urgent | 92 |\n| high | 100 |')
    expect(blocks).toHaveLength(1)
    const table = blocks[0]
    expect(table?.type).toBe('table')
    if (table?.type !== 'table') return
    expect(table.head.map(cell => cell.map(span => span.text))).toEqual([['Priority'], ['Tickets']])
    expect(table.rows).toHaveLength(2)
    expect(table.rows[0]?.[1]?.[0]?.text).toBe('92')
  })

  it('parses bullet and numbered lists as separate blocks', () => {
    const blocks = parseMarkdown('- one\n- two\n\n1. first\n2. second')
    expect(blocks.map(block => block.type)).toEqual(['list', 'list'])
    expect(blocks[0]).toMatchObject({ type: 'list', ordered: false })
    expect(blocks[1]).toMatchObject({ type: 'list', ordered: true })
  })

  it('keeps fenced code verbatim, including the language tag', () => {
    const blocks = parseMarkdown('Before\n```python\nx = 1\ny = 2\n```\nAfter')
    expect(blocks.map(block => block.type)).toEqual(['paragraph', 'code', 'paragraph'])
    const code = blocks[1]
    expect(code).toMatchObject({ type: 'code', text: 'x = 1\ny = 2', lang: 'python' })
  })

  it('treats plain prose as one paragraph and never returns raw asterisks', () => {
    const blocks = parseMarkdown('There are **420** tickets in `tickets_cases.csv`.')
    expect(blocks).toHaveLength(1)
    const text = markdownToText('There are **420** tickets in `tickets_cases.csv`.')
    expect(text).toBe('There are 420 tickets in tickets_cases.csv.')
  })

  it('returns no blocks for empty content', () => {
    expect(parseMarkdown('   \n\n ')).toEqual([])
  })
})
