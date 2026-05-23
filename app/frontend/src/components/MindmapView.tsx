import { useEffect, useRef } from 'react'
import { Transformer } from 'markmap-lib'
import { Markmap } from 'markmap-view'

const transformer = new Transformer()

interface Props {
  text: string
  title?: string
}

export default function MindmapView({ text, title }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const mmRef = useRef<Markmap | null>(null)

  useEffect(() => {
    if (!svgRef.current) return

    const { root } = transformer.transform(text)

    if (mmRef.current) {
      mmRef.current.setData(root).then(() => mmRef.current?.fit())
    } else {
      const mm = Markmap.create(svgRef.current, {
        embedGlobalCSS: true,
        fitRatio: 0.95,
        duration: 300,
      })
      mmRef.current = mm
      mm.setData(root).then(() => mm.fit())
    }
  }, [text])

  useEffect(() => {
    return () => {
      mmRef.current?.destroy()
      mmRef.current = null
    }
  }, [])

  function exportSvg() {
    const svg = svgRef.current
    if (!svg) return

    // Clone so we can set explicit dimensions without affecting the live view
    const clone = svg.cloneNode(true) as SVGSVGElement
    const { width, height } = svg.getBoundingClientRect()
    clone.setAttribute('width', String(Math.round(width)))
    clone.setAttribute('height', String(Math.round(height)))

    // Embed a white background rect so the export isn't transparent
    const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
    bg.setAttribute('width', '100%')
    bg.setAttribute('height', '100%')
    bg.setAttribute('fill', '#1a1d23')   // matches --bg dark theme
    clone.insertBefore(bg, clone.firstChild)

    const blob = new Blob(
      ['<?xml version="1.0" encoding="UTF-8"?>\n' + clone.outerHTML],
      { type: 'image/svg+xml' }
    )
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const slug = (title ?? 'mindmap').replace(/[^a-z0-9]+/gi, '-').toLowerCase().slice(0, 60)
    a.href = url
    a.download = `${slug}-mindmap.svg`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mindmap-wrap">
      <div className="mindmap-toolbar">
        <button className="mindmap-export-btn" onClick={exportSvg} title="Download mindmap as SVG">
          ↓ Export SVG
        </button>
        <button className="mindmap-export-btn" onClick={() => mmRef.current?.fit()} title="Reset zoom and fit to view">
          ⊡ Fit
        </button>
      </div>
      <svg ref={svgRef} className="mindmap-svg" />
    </div>
  )
}
