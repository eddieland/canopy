import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link, useLocation } from '@tanstack/react-router'
import { MessageSquareReply } from 'lucide-react'
import { useEffect } from 'react'

import { unsentDraftsQuery } from '@/api/queries'
import type { UnsentDrafts } from '@/api/types'
import { Age } from '@/components/age'
import { Code } from '@/components/code'
import { MemoryText } from '@/components/memory-text'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { ListRow, RowList } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { TicketDrafts } from '@/components/ticket-drafts'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Button } from '@/components/ui/button'
import {
    DRAFT_TONE,
    DRAFTS_ANCHOR,
    draftAnchor,
    draftGoes,
    draftLine,
    draftsText,
    longestWaiting,
    unsentAnchor,
    unsentCount,
} from '@/lib/drafts'
import { pullRequestLabel } from '@/lib/pull-request-label'

/**
 * Every draft that waits on the operator (DESIGN §29), the replies runs wrote in place of posting them, by the PR or
 * the ticket each is for, the longest waiting first: what the attention list counts as `drafts_waiting`, listed whole.
 * A PR's drafts are rows that open their cards on its page, where they are sent together; a ticket's own are their
 * cards, sent here.
 */
export const Route = createFileRoute('/pull-requests/drafts')({
    component: DraftsPage,
})

function DraftsPage() {
    const query = useQuery(unsentDraftsQuery)
    const { data } = query
    // A ticket's chip links to its group (`#drafts-ABC-099`), which is not drawn until the drafts are read: brought
    // into view once it is.
    const hash = useLocation({ select: (location) => location.hash })
    const read = data !== undefined
    useEffect(() => {
        if (read && hash !== '') {
            document.querySelector(`#${CSS.escape(hash)}`)?.scrollIntoView({ block: 'start' })
        }
    }, [hash, read])
    return (
        <>
            <PageHeader title="Drafts">
                The replies your runs wrote and left for you to send, the longest waiting first. A PR&apos;s go out
                together from its page, as one review in your name; a ticket&apos;s own are sent here. Nothing posts
                until you send it, with <Code>trust.review_replies = &quot;approve&quot;</Code>.
            </PageHeader>
            <Panel>
                <PanelHeader label="Unsent drafts">
                    <span className="readout text-xs text-muted-foreground" data-testid="unsent-drafts-count">
                        {data === undefined ? '' : unsentCount(data)}
                    </span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelLoading query={query} className="min-h-72" />
                ) : data.length === 0 ? (
                    <Empty size="panel">no draft waits on you: every reply a run wrote was sent or dropped</Empty>
                ) : (
                    <div className="divide-y" data-testid="unsent-drafts">
                        {longestWaiting(data).map((group, index, groups) => (
                            <Group
                                key={`${group.ticket_key} ${group.pr_url ?? ''}`}
                                group={group}
                                // A ticket's chip jumps to the first of its groups.
                                anchored={groups.findIndex((g) => g.ticket_key === group.ticket_key) === index}
                            />
                        ))}
                    </div>
                )}
            </Panel>
        </>
    )
}

/**
 * One PR's drafts, or one ticket's own: a head line naming it, its ticket, how long the oldest has waited, and for a
 * PR the button to its page, then the drafts. `anchored` gives it the id its ticket's chip links to.
 */
function Group({ group, anchored }: { group: UnsentDrafts; anchored: boolean }) {
    const url = group.pr_url ?? null
    return (
        <section
            id={anchored ? unsentAnchor(group.ticket_key) : undefined}
            className="scroll-mt-16"
            aria-label={url === null ? `Drafts for ${group.ticket_key}` : `Drafts for ${pullRequestLabel(url)}`}
            data-testid="unsent-drafts-group"
        >
            <header className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5">
                {url === null ? (
                    <span className="font-mono text-xs text-muted-foreground">for the ticket</span>
                ) : (
                    <PullRequestLink url={url} className="shrink-0" />
                )}
                <span className="flex min-w-0 flex-1 items-center gap-2">
                    <TicketLink ticketKey={group.ticket_key} className="shrink-0" />
                    <TicketTitle title={group.ticket_title ?? null} />
                </span>
                <Chip tone="blocked">{draftsText(group.drafts.length)}</Chip>
                <Age at={group.since} className="min-w-12 text-right" />
                {url !== null && (
                    <Button asChild size="sm" variant="outline">
                        <Link to="/pull-requests/pr" search={{ url }} hash={DRAFTS_ANCHOR}>
                            <MessageSquareReply />
                            Read and send
                        </Link>
                    </Button>
                )}
            </header>
            {url === null ? (
                <TicketDrafts ticketKey={group.ticket_key} drafts={group.drafts} bare className="pt-0" />
            ) : (
                <RowList kind="thread-draft" as="ol" className="divide-y border-t border-dashed">
                    {group.drafts.map((draft) => (
                        <ListRow key={draftAnchor(draft)} kind="thread-draft" className="py-2 text-sm">
                            <Chip tone={DRAFT_TONE[draft.status]} word={draft.status} className="justify-center" />
                            <span className="readout text-xs text-muted-foreground">
                                <RunLink id={draft.run} /> {draft.number}
                            </span>
                            <Link
                                to="/pull-requests/pr"
                                search={{ url }}
                                hash={draftAnchor(draft)}
                                className="min-w-0 truncate text-accent underline-offset-4 hover:underline"
                            >
                                <MemoryText text={draftLine(draft)} className="whitespace-nowrap" />
                            </Link>
                            <span className="font-mono text-xs text-muted-foreground">{draftGoes(draft)}</span>
                        </ListRow>
                    ))}
                </RowList>
            )}
        </section>
    )
}
