import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { renderText } from '../utils/renderText'

// Wrap in a plain div so render() has a single root
function renderWithDiv(text: string) {
  const nodes = renderText(text)
  return render(<div>{nodes}</div>)
}

describe('renderText', () => {
  it('renders a ## heading as h3', () => {
    renderWithDiv('## Chapter Title\n\nSome body text.')
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Chapter Title')
  })

  it('renders plain text as a paragraph', () => {
    const { container } = renderWithDiv('Just some plain text without headings.')
    const paras = container.querySelectorAll('p.text-paragraph')
    expect(paras.length).toBe(1)
    expect(paras[0].textContent).toBe('Just some plain text without headings.')
  })

  it('renders the heading body as a paragraph too', () => {
    const { container } = renderWithDiv('## Title\n\nBody content here.')
    const h3 = container.querySelector('h3.chapter-heading')
    expect(h3).not.toBeNull()
    expect(h3?.textContent).toBe('Title')
    const p = container.querySelector('p.text-paragraph')
    expect(p?.textContent).toBe('Body content here.')
  })

  it('does not crash on empty string', () => {
    expect(() => renderWithDiv('')).not.toThrow()
  })

  it('does not crash on whitespace-only string', () => {
    expect(() => renderWithDiv('   \n\n   ')).not.toThrow()
  })

  it('renders multiple paragraphs', () => {
    const { container } = renderWithDiv('First paragraph.\n\nSecond paragraph.')
    const paras = container.querySelectorAll('p.text-paragraph')
    expect(paras.length).toBe(2)
  })

  it('renders multiple chapters', () => {
    const text = '## Chapter One\n\nContent for chapter one.\n\n## Chapter Two\n\nContent for chapter two.'
    const { container } = renderWithDiv(text)
    const headings = container.querySelectorAll('h3.chapter-heading')
    expect(headings.length).toBe(2)
  })
})
