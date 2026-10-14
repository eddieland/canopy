import type { ReactNode } from 'react'

import { LinkOutIcon } from '@/components/link-out-icon'
import type { ChoreFinding, ChoreRunFinding } from '@/api/types'
import { Age } from '@/components/age'
import { useDismissFinding } from '@/components/dismiss-finding'
import { LinkedText } from '@/components/linked-text'
import { ListRow, RowLine } from '@/components/rows'
import { Chip } from '@/components/status'
import { cn } from '@/lib/utils'

/**
 * A chore's finding: its id, its title and link, and below them its detail; an open finding also says how long it has
 * been open. All of it is the agent's: text, never markup. Given its `chore`, an open finding also says whether the
 * operator dismissed it, with a small button in its head line to dismiss it or list it again.
 */
export function ChoreFindingRow({ finding, chore }: { finding: ChoreFinding | ChoreRunFinding; chore?: string }) {
    if (chore !== undefined && 'since' in finding) {
        return <OpenFindingRow chore={chore} finding={finding} />
    }
    return <FindingRow finding={finding} />
}

function OpenFindingRow({ chore, finding }: { chore: string; finding: ChoreFinding }) {
    const { button, notice } = useDismissFinding(chore, finding.id, finding.dismissed)
    return <FindingRow finding={finding} action={button} notice={notice} />
}

function FindingRow({
    finding,
    action,
    notice,
}: {
    finding: ChoreFinding | ChoreRunFinding
    action?: ReactNode
    notice?: ReactNode
}) {
    const open = 'since' in finding ? finding : null
    return (
        <ListRow kind="finding" data-testid={`finding-${finding.id}`}>
            <Chip>{finding.id}</Chip>
            <span className="truncate text-sm">{finding.title}</span>
            <span className="flex items-center justify-end gap-3">
                {open?.dismissed && <Chip>dismissed</Chip>}
                {open && <Age at={open.since} />}
                {action}
            </span>
            {finding.detail && (
                <RowLine from="title" className="text-sm break-words whitespace-pre-wrap text-muted-foreground">
                    <LinkedText text={finding.detail} />
                </RowLine>
            )}
            {finding.link && (
                <RowLine from="title">
                    <a
                        href={finding.link}
                        target="_blank"
                        rel="noreferrer noopener"
                        className={cn(
                            'inline-flex items-center gap-1 font-mono text-xs text-accent underline-offset-4',
                            'hover:underline',
                        )}
                    >
                        {finding.link.replace(/^https:\/\//u, '')}
                        <LinkOutIcon href={finding.link} />
                    </a>
                </RowLine>
            )}
            {/* Hidden while the notice says nothing, so it adds no gap under the row. */}
            <RowLine from="title" className="empty:hidden">
                {notice}
            </RowLine>
        </ListRow>
    )
}
