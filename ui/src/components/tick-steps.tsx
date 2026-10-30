import { Link } from '@tanstack/react-router'
import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { tickRef } from '@/lib/refs'

/**
 * A tick page's step to the tick before it and the tick after it, by id, dry runs included: each a link that names
 * the tick it goes to. At either end its button stays, disabled, and says on hover that there is none, so the pair
 * never shifts. The latest tick has no button of its own: the header's readout links there.
 */
export function TickSteps({ previous, next }: { previous: number | null; next: number | null }) {
    return (
        <nav aria-label="Neighbouring ticks" className="flex items-center gap-1">
            <Step id={previous} older />
            <Step id={next} older={false} />
        </nav>
    )
}

function Step({ id, older }: { id: number | null; older: boolean }) {
    const chevron = older ? <ChevronLeft aria-hidden /> : <ChevronRight aria-hidden />
    if (id === null) {
        const title = older ? 'no older tick: this is the first' : 'no newer tick yet: this is the latest'
        return (
            // A disabled button takes no pointer, so its title is its wrapper's too, to show on hover.
            <span title={title}>
                <Button variant="ghost" size="xs" disabled title={title}>
                    {older && chevron}
                    {older ? 'older' : 'newer'}
                    {!older && chevron}
                </Button>
            </span>
        )
    }
    return (
        <Button asChild variant="ghost" size="xs">
            <Link
                to="/workspace/ticks/$id"
                params={{ id: String(id) }}
                title={older ? 'the tick before this one' : 'the tick after this one'}
            >
                {older && chevron}
                {tickRef(id)}
                {!older && chevron}
            </Link>
        </Button>
    )
}
