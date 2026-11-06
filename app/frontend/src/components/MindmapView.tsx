import { useEffect, useRef } from 'react'
import { Transformer } from 'markmap-lib'
import { Markmap } from 'markmap-view'
import { fitMindmap } from './mindmapFit'

const transformer = new Transformer()

function hasSize(el: Element): boolean {
  const r = el.getBoundingClientRect()
  return r.width > 0 && r.height > 0
}

interface Props {
  text: string
  title?: string
  onRegenerate?: () => void
}

export default function MindmapView({ text, title, onRegenerate }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const mmRef = useRef<Markmap | null>(null)

  // markmap measures the svg: drawn while the svg is hidden or has no size (a tab being switched, a lazy chunk still loading) it
  // throws SVGLength errors and lays out at NaN / a tiny scale (NS-17 items 7, 10, 16). So it is drawn only once the svg has a
  // size, fitted at a readable scale (mindmapFit.ts), and fitted again whenever the size changes (the tab becomes visible, the
  // window is resized). A change to a hidden (zero) size does nothing.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    let observer: ResizeObserver | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    const later: Array<ReturnType<typeof setTimeout>> = []      // retry and settle timers, all cleared when this effect ends
    let gone = false
    let fittedAt = ''

    // Fit; if markmap has not positioned the nodes yet (its first layout is still going) try again a moment later.
    const refit = (mm: Markmap, attempt = 0) => {
      if (gone || mmRef.current !== mm || !hasSize(svg)) return
      const { width, height } = svg.getBoundingClientRect()
      fittedAt = `${Math.round(width)}x${Math.round(height)}`
      void fitMindmap(mm as never, svg).then(fitted => {
        if (!fitted && attempt < 6 && !gone && mmRef.current === mm) later.push(setTimeout(() => refit(mm, attempt + 1), 150))
      })
    }

    const draw = () => {
      const { root } = transformer.transform(text.replace(/</g, '&lt;'))
      const box = svg.getBoundingClientRect()
      fittedAt = `${Math.round(box.width)}x${Math.round(box.height)}`      // (the fit after setData is for this size)
      let mm = mmRef.current
      const created = !mm
      if (!mm) {
        mm = Markmap.create(svg, {
          embedGlobalCSS: true,
          fitRatio: 0.9,
          duration: 300,
          maxWidth: 360,
          initialExpandLevel: 3,
        })
        mmRef.current = mm
      }
      const shown = mm
      shown.setData(root).then(() => refit(shown))
      if (!created) return
      later.push(setTimeout(() => refit(shown), 450))             // once more when markmap's first transition (300 ms) is over
    }

    const sizeChanged = () => {
      if (gone) return
      if (!hasSize(svg)) return                                  // hidden: wait for the next size
      if (!mmRef.current) { draw(); return }                     // first time it has a size
      const { width, height } = svg.getBoundingClientRect()
      if (`${Math.round(width)}x${Math.round(height)}` === fittedAt) return
      if (timer) clearTimeout(timer)
      const mm = mmRef.current
      timer = setTimeout(() => refit(mm), 120)                   // a resize drag fires many times: fit once it settles
    }

    if (hasSize(svg)) draw()
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(sizeChanged)
      observer.observe(svg)
    } else if (!hasSize(svg)) {
      draw()                                                      // (no ResizeObserver: draw as before)
    }
    return () => { gone = true; if (timer) clearTimeout(timer); later.forEach(clearTimeout); observer?.disconnect() }
  }, [text])

  useEffect(() => {
    return () => { mmRef.current?.destroy(); mmRef.current = null }
  }, [])

  function exportSvg() {
    const svg = svgRef.current
    if (!svg) return
    const clone = svg.cloneNode(true) as SVGSVGElement
    const { width, height } = svg.getBoundingClientRect()
    clone.setAttribute('width', String(Math.round(width)))
    clone.setAttribute('height', String(Math.round(height)))
    const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
    bg.setAttribute('width', '100%')
    bg.setAttribute('height', '100%')
    bg.setAttribute('fill', '#1a1d23')
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
        <button className="mindmap-export-btn" onClick={() => { if (svgRef.current && mmRef.current) void fitMindmap(mmRef.current as never, svgRef.current) }} title="Reset zoom">
          ⊡ Fit
        </button>
        {onRegenerate && (
          <button className="mindmap-export-btn" onClick={onRegenerate} title="Re-generate mindmap via LLM">
            ↺ Re-generate
          </button>
        )}
      </div>
      <svg ref={svgRef} className="mindmap-svg" />
    </div>
  )
}
