import { useQueryClient } from '@tanstack/react-query'

import { refreshTicketDrafts } from '@/api/mutations'
import type { Draft } from '@/api/types'
import { Panel, PanelHeader } from '@/components/panel'
import { DraftCard } from '@/components/review-threads'
import { cn } from '@/lib/utils'

/**
 * A ticket's own drafts (DESIGN §29): the comments its runs would have posted on it, a question when blocked or what a
 * run did, each with the issue it goes to and its verbs, as a PR's are on its threads. Nothing when it has none, which
 * is every ticket until a `tracker` source has a post command. `bare` draws the cards without a panel of their own, as
 * an attention item's detail does.
 */
export function TicketDrafts({
    ticketKey,
    drafts,
    bare = false,
    className,
}: {
    ticketKey: string
    drafts: Draft[]
    bare?: boolean
    className?: string
}) {
    const client = useQueryClient()
    if (drafts.length === 0) {
        return null
    }
    const changed = () => void refreshTicketDrafts(client, ticketKey)
    const cards = (
        <div className={cn('flex flex-col gap-2 p-3', bare && className)} data-testid="ticket-drafts">
            {drafts.map((d) => (
                <DraftCard key={`${d.run}-${d.number}`} draft={d} onChange={changed} />
            ))}
        </div>
    )
    if (bare) {
        return cards
    }
    return (
        <Panel className={className}>
            <PanelHeader label="Drafts for the ticket">
                <span className="readout text-xs text-muted-foreground">{drafts.length}</span>
            </PanelHeader>
            {cards}
        </Panel>
    )
}
