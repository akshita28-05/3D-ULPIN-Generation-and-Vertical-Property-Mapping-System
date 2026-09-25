import { useCallback, useRef, useState } from 'react'

export default function useDraggable() {
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const drag = useRef(null)

  const onPointerDown = useCallback((e) => {
    drag.current = { startX: e.clientX, startY: e.clientY, origin: offset }
    e.currentTarget.setPointerCapture?.(e.pointerId)
    e.stopPropagation()
  }, [offset])

  const onPointerMove = useCallback((e) => {
    if (!drag.current) return
    const { startX, startY, origin } = drag.current
    setOffset({ x: origin.x + (e.clientX - startX), y: origin.y + (e.clientY - startY) })
  }, [])

  const onPointerUp = useCallback((e) => {
    drag.current = null
    e.currentTarget.releasePointerCapture?.(e.pointerId)
  }, [])

  return {
    style: (offset.x || offset.y) ? { transform: `translate(${offset.x}px, ${offset.y}px)` } : undefined,
    handleProps: {
      onPointerDown, onPointerMove, onPointerUp,
      style: { touchAction: 'none', cursor: 'grab' },
      title: 'Drag to move',
    },
  }
}
