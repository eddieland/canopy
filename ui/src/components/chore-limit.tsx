import { ListFilter } from 'lucide-react'

import type { ChoreSummary } from '@/api/types'
import { InlineCode } from '@/components/rich-text'
import { overLimitText } from '@/lib/chores'
import { cn } from '@/lib/utils'

/**
 * A chore over its finding limit (docs/design §19): its latest ok run found more than its `max_findings` and listed
 * only those, so the band heads its page, by how much and what to do, for as long as the runs keep finding more.
 */
export function ChoreLimitBanner({ chore }: { chore: Pick<ChoreSummary, 'name' | 'max_findings' | 'more_findings'> }) {
    if (chore.more_findings <= 0) {
        return null
    }
    return (
        <section
            aria-label="Over its finding limit"
            data-testid="chore-limit"
            className={cn(
                'flex items-start gap-3 rounded-md border px-3 py-2',
                'border-status-blocked/40 bg-status-blocked/8',
            )}
        >
            <ListFilter aria-hidden className="mt-0.5 size-4 shrink-0 text-status-blocked" />
            <div className="flex min-w-0 flex-col gap-0.5">
                <p className="text-sm break-words">
                    <span className="font-medium text-status-blocked">Over its finding limit: </span>
                    {overLimitText(chore.max_findings, chore.more_findings)}
                </p>
                <p className="text-xs text-muted-foreground">
                    <InlineCode text={fixText(chore.name)} />
                </p>
            </div>
        </section>
    )
}

// What the operator can do about it, naming the chore's config table.
function fixText(name: string): string {
    return `Raise \`max_findings\` in \`[chores.${name}]\`, or narrow what it reports with a note.`
}
