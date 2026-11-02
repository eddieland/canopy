import { cn } from '@/lib/utils'

/** The letters an agent's options go by, in order: a run's question's, and a plan's open decision's. */
export const LETTERS = ['A', 'B', 'C', 'D', 'E'] as const

/**
 * A row of an agent's lettered options: what `LetteredOption` sits in, as a `div`, a button that answers with it, or a
 * radio that picks it. The interactive kinds add `OPTION_HOVER`.
 */
export const OPTION_ROW = 'flex w-full items-start gap-2.5 rounded-sm px-2 py-1 text-left text-sm'

/** What an option row that does something adds to `OPTION_ROW`: a raised hover and the focus ring. */
export const OPTION_HOVER = cn(
    'hover:bg-surface-raised focus-visible:ring-2 focus-visible:ring-ring',
    'outline-none disabled:opacity-50',
)
