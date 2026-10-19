import { cn } from '@/lib/utils'

/**
 * The leaf a cleared attention item drops (ui/DESIGN.md, "Fun"): one of the empty inbox's leaves, drifting off and
 * fading, once, as it mounts. Place it with `className`, absolutely, over room it may pass through: it takes no
 * pointer, is hidden from a screen reader, and under reduced motion is not shown at all. A new `key` plays it again.
 */
export function Leaf({ className }: { className?: string }) {
    return (
        <svg
            aria-hidden
            viewBox="0 0 20 20"
            data-testid="leaf"
            className={cn(
                'pointer-events-none absolute size-5 overflow-visible text-accent motion-reduce:hidden',
                className,
            )}
        >
            <ellipse cx="10" cy="10" rx="4.5" ry="2.2" fill="currentColor" className="animate-leaf-off" />
        </svg>
    )
}
