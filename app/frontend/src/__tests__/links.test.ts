import { describe, it, expect } from 'vitest'
import { linkOfLine, parseLinks } from '../utils/links'

describe('parseLinks', () => {
  it('one link per line, in the order typed', () => {
    expect(parseLinks('https://youtu.be/a\nhttps://youtu.be/b')).toEqual(['https://youtu.be/a', 'https://youtu.be/b'])
  })

  it('drops blank lines, spaces and Windows line ends; a lone link is a list of one', () => {
    expect(parseLinks('  https://youtu.be/a  \r\n\r\n   \r\nhttps://youtu.be/b\r\n')).toEqual(['https://youtu.be/a', 'https://youtu.be/b'])
    expect(parseLinks('https://youtu.be/a')).toEqual(['https://youtu.be/a'])
    expect(parseLinks('')).toEqual([])
  })

  it('keeps only the link of "URL | title", "title: URL," and quoted lines', () => {
    expect(linkOfLine('https://youtu.be/a | A title')).toBe('https://youtu.be/a')
    expect(linkOfLine('Watch: "https://youtu.be/a",')).toBe('https://youtu.be/a')
    expect(linkOfLine('https://youtu.be/a.')).toBe('https://youtu.be/a')
  })

  it('a line without a link is passed on as it is, so the server can say it is not a YouTube link', () => {
    expect(parseLinks('not a link\nhttps://youtu.be/a')).toEqual(['not a link', 'https://youtu.be/a'])
  })
})
