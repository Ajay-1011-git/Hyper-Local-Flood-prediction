/**
 * PixelIcon — a tiny bitmap-grid icon renderer for the pixel-art design
 * system (T4C theme pass).
 *
 * WHY HAND-BUILT, NOT HEROICONS/LUCIDE
 * ---------------------------------------------------------------
 * This project's chosen visual language is hard-edged pixel-art (no
 * border-radius, no blur — see index.css's own docstring). Heroicons/
 * Lucide's smooth rounded-stroke icon language would visually clash with
 * that as badly as a photo would clash with a flat illustration. Each
 * icon here is a small bitmap (one string per row, `1`=filled) rendered
 * as a grid of `<rect>`s — crisp at any size, no rasterised PNG to blur,
 * themeable via `currentColor` exactly like a normal icon font/SVG set.
 *
 * Adding a new icon is just adding a new bitmap to `ICONS` below — no
 * hand-drawn bezier paths required.
 */

const ICONS = {
  /** The app's own pixel logo mark — a stylised water drop. */
  drop: [
    '....1....',
    '...111...',
    '..11111..',
    '..11111..',
    '.1111111.',
    '.1111111.',
    '.1111111.',
    '.1111111.',
    '..11111..',
    '..11111..',
    '...111...',
  ],
} as const

export type PixelIconName = keyof typeof ICONS

export interface PixelIconProps {
  name: PixelIconName
  /** Rendered size in CSS pixels (square). */
  size?: number
  className?: string
  /** Real accessible label — icons here are always decorative alongside
   *  real text elsewhere on the page (this project's own rule: never
   *  color/icon alone), so `aria-hidden` is the default; pass a label
   *  only when this icon is the ONLY content conveying meaning. */
  title?: string
}

export function PixelIcon({ name, size = 24, className = '', title }: PixelIconProps) {
  const bitmap = ICONS[name]
  const rows = bitmap.length
  const cols = bitmap[0].length

  const cells: { x: number; y: number }[] = []
  bitmap.forEach((row, y) => {
    for (let x = 0; x < row.length; x += 1) {
      if (row[x] === '1') cells.push({ x, y })
    }
  })

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${cols} ${rows}`}
      className={`pixel-crisp ${className}`.trim()}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
    >
      {title ? <title>{title}</title> : null}
      {cells.map((cell) => (
        <rect key={`${cell.x}-${cell.y}`} x={cell.x} y={cell.y} width={1} height={1} fill="currentColor" />
      ))}
    </svg>
  )
}

export default PixelIcon
