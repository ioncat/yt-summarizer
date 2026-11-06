import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// NS-17 item 7: markmap draws its text with its own colour (#333), which cannot be read on the dark theme. The mind map must take
// its colours from the theme variables, which have a light and a dark value (jsdom has no layout or colours, so the stylesheet
// itself is checked).
const css = readFileSync(resolve(__dirname, '..', 'index.css'), 'utf8')
const rule = css.slice(css.indexOf('svg.mindmap-svg.markmap'))

describe('mind map colours (NS-17 item 7)', () => {
  it('the text colour comes from the theme, not from markmap\'s default', () => {
    expect(rule).toMatch(/--markmap-text-color:\s*var\(--text\)/)
  })

  it('the rule is more specific than markmap\'s own .markmap rule, so it wins', () => {
    expect(css).toMatch(/svg\.mindmap-svg\.markmap\s*\{/)
  })

  it('the theme variable it uses has a different value in the dark theme', () => {
    const light = css.match(/:root\s*\{[^}]*--text:\s*(#[0-9a-f]+)/s)?.[1]
    const dark = css.match(/\.dark\s*\{[^}]*--text:\s*(#[0-9a-f]+)/s)?.[1]
    expect(light).toBeTruthy()
    expect(dark).toBeTruthy()
    expect(dark).not.toBe(light)
  })
})
