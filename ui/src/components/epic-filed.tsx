import type { EpicSummary } from '@/api/types'
import { Leaf } from '@/components/leaf'
import { breakdownFull, entriesFiled } from '@/lib/epics'
import { useFilledMoment } from '@/lib/filled-epics'
import { cn } from '@/lib/utils'

/**
 * How much of an epic's breakdown is filed, in its page's header (`4 of 4 entries filed`), and the small reward for
 * filing the last of it (ui/DESIGN.md, "Fun"): the first time this browser shows the breakdown full, live or on the
 * first visit after, the readout lights in the accent's tint, which fades, and drops a leaf, as a cleared attention
 * item does, once (`useFilledMoment`). It shows only what the journal says, so it never celebrates a member a refusal
 * left out, and nothing waits on it; under reduced motion it holds still, and a screenshot sees it at rest.
 */
export function EntriesFiled({ epic }: { epic: EpicSummary }) {
    const playing = useFilledMoment(epic.id, breakdownFull(epic))
    return (
        <span
            data-testid="entries-filed"
            // Lit, it takes a hair of room either side for its tint and gives it back, so nothing beside it moves.
            className={cn('relative', playing && '-mx-1 box-decoration-clone rounded-sm px-1 animate-lit')}
        >
            {entriesFiled(epic)}
            {playing && <Leaf className="-top-2 -right-3" />}
        </span>
    )
}
