// Skeleton: quiet loading placeholders, a single bar or a block of text lines.

export interface SkeletonProps {
  width?: number | string
  height?: number | string
  lines?: number
  className?: string
}

/** One placeholder bar, or `lines` bars of decreasing width that stand in for a paragraph. */
export function Skeleton({ width = '100%', height = 14, lines, className }: SkeletonProps) {
  if (lines && lines > 1) {
    return (
      <span className={['r-skel-lines', className ?? ''].join(' ')} aria-hidden="true">
        {Array.from({ length: lines }, (_, i) => (
          <span key={i} className="r-skel" style={{ width: i === lines - 1 ? '62%' : '100%', height }} />
        ))}
      </span>
    )
  }
  return <span className={['r-skel', className ?? ''].join(' ')} style={{ width, height }} aria-hidden="true" />
}
