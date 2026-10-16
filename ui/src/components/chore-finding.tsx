import type { ReactNode } from 'react'

import { LinkOutIcon } from '@/components/link-out-icon'
import type { ChoreFinding, ChoreRunFinding } from '@/api/types'
import { Age } from '@/components/age'
import { useDismissFinding } from '@/components/dismiss-finding'
import { LinkedText } from '@/components/linked-text'
import { PullRequestLink } from '@/components/pull-request-link'
import { ListRow, RowLine } from '@/components/rows'
import { Chip } from '@/components/status'
import { addressOf } from '@/lib/links'
import { isPullRequest } from '@/lib/pull-request-label'
import { cn } from '@/lib/utils'

/**
 * A chore's finding: its id and its title, and below them its detail and link; an open finding also says how long it
 * has been open. All of it is the agent's: text, never markup. Given its `chore`, an open finding also says whether the
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
        // Level with the first line of a title that wraps, as a field's label is (`Fields`).
        <ListRow kind="finding" className="items-baseline" data-testid={`finding-${finding.id}`}>
            {/*
             * The agent's own id for it: journal text, so muted data, never a chip. A long one wraps down beside the
             * detail, not below the title, so it opens no gap between the two.
             */}
            <span className="row-span-2 font-mono text-xs break-all text-muted-foreground">{finding.id}</span>
            {/* Whole, never cut: it is up to 200 characters, and the finding's name. */}
            <span className="text-sm break-words">{finding.title}</span>
            <span className="flex items-center justify-end gap-3">
                {open?.dismissed && <Chip>dismissed</Chip>}
                {open && <Age at={open.since} />}
                {action}
            </span>
            {finding.detail && (
                <RowLine from="title" className="text-sm break-words whitespace-pre-wrap text-muted-foreground">
                    <LinkedText text={finding.detail} pullRequests />
                </RowLine>
            )}
            {finding.link && (
                <RowLine from="title">
                    <FindingLink href={finding.link} />
                </RowLine>
            )}
            {/* Hidden while the notice says nothing, so it adds no gap under the row. */}
            <RowLine from="title" className="empty:hidden">
                {notice}
            </RowLine>
        </ListRow>
    )
}

/**
 * A chore's finding on its own, out of a list, as the attention page shows it: its title whole, then its detail and
 * its link, each on its own line rather than run together. All of it is the agent's text.
 */
export function ChoreFindingText({ finding }: { finding: ChoreFinding }) {
    return (
        <div className="flex flex-col gap-1.5" data-testid="finding-text">
            <p className="text-sm font-semibold break-words">{finding.title}</p>
            {finding.detail && (
                <p className="text-sm break-words whitespace-pre-wrap text-muted-foreground">
                    <LinkedText text={finding.detail} pullRequests />
                </p>
            )}
            {finding.link && <FindingLink href={finding.link} />}
        </div>
    )
}

// A PR as it is named anywhere; any other link as its address and its icon.
function FindingLink({ href }: { href: string }) {
    if (isPullRequest(href)) {
        return <PullRequestLink url={href} className="self-start" />
    }
    return (
        <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className={cn(
                'inline-flex items-center gap-1 self-start font-mono text-xs text-accent underline-offset-4',
                'hover:underline',
            )}
        >
            {addressOf(href)}
            <LinkOutIcon href={href} />
        </a>
    )
}
