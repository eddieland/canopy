import { cn } from '@/lib/utils'

/**
 * The toggle under text cut to its first lines, which says how many it holds back: `show 3 more lines`, then
 * `show less`. It shows more of text already on screen rather than opening a part of the page, so it is a plain button
 * with `aria-expanded`, in the accent, not a `Disclosure` (DESIGN.md). Rich text and a transcript's thinking use it.
 */
export function MoreLines({ hidden, open, onToggle }: { hidden: number; open: boolean; onToggle: () => void }) {
    return (
        <button
            type="button"
            aria-expanded={open}
            onClick={onToggle}
            className={cn(
                'self-start rounded-sm font-mono text-xs text-accent not-italic underline-offset-4 outline-none',
                'hover:underline focus-visible:ring-3 focus-visible:ring-ring/50',
            )}
        >
            {open ? 'show less' : `show ${hidden} more ${hidden === 1 ? 'line' : 'lines'}`}
        </button>
    )
}
