import { useEffect, useRef } from 'react'
import { Transformer } from 'markmap-lib'
import { Markmap } from 'markmap-view'

const transformer = new Transformer()

interface Props {
  text: string
}

export default function MindmapView({ text }: Props) {
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

  return (
    <div className="mindmap-wrap">
      <svg ref={svgRef} className="mindmap-svg" />
    </div>
  )
}
