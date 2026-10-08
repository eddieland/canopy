import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { attentionQuery } from '@/api/queries'
import type { AttentionItem } from '@/api/types'
import { Age } from '@/components/age'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { Chip } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Skeleton } from '@/components/ui/skeleton'

export const Route = createFileRoute('/attention')({
    component: AttentionPage,
})

function AttentionPage() {
    const { data } = useQuery(attentionQuery)
    const items = data?.filter((i) => !i.finding)
    const findings = data?.filter((i) => i.finding)
    const reasons = [...new Set(items?.map((i) => i.reason))].toSorted()
    const chores = [...new Set(findings?.map((i) => i.subject))].toSorted()
    return (
        <>
            <PageHeader label="Inbox" title="Attention">
                What needs you, as <code className="font-mono text-xs">canopy status</code> lists it. An item leaves
                when its cause is gone.
            </PageHeader>
            {data === undefined && (
                <Panel>
                    <PanelHeader label="Loading" />
                    <div className="flex flex-col gap-2 p-3">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-4 w-1/2" />
                    </div>
                </Panel>
            )}
            {data !== undefined && data.length === 0 && (
                <Panel>
                    <Placeholder className="min-h-40">Nothing needs you.</Placeholder>
                </Panel>
            )}
            {reasons.map((reason) => (
                <Group key={reason} label={reason} items={items?.filter((i) => i.reason === reason) ?? []} />
            ))}
            {chores.map((chore) => (
                <Group
                    key={chore}
                    label={`${chore} findings`}
                    items={findings?.filter((i) => i.subject === chore) ?? []}
                />
            ))}
        </>
    )
}

function Group({ label, items }: { label: string; items: AttentionItem[] }) {
    return (
        <Panel data-testid={`attention-${label}`}>
            <PanelHeader label={label}>
                <span className="readout text-xs text-muted-foreground">{items.length}</span>
            </PanelHeader>
            <ul className="divide-y">
                {items.map((item) => (
                    <li
                        key={item.id}
                        className="grid grid-cols-[9rem_minmax(0,1fr)_3rem] items-baseline gap-3 px-3 py-2.5"
                    >
                        <span className="truncate">
                            {item.ticket_key ? (
                                <TicketLink ticketKey={item.ticket_key} />
                            ) : item.finding ? (
                                <Chip>{item.reason}</Chip>
                            ) : (
                                <span className="font-mono text-xs">{item.subject}</span>
                            )}
                        </span>
                        <p className="text-sm break-words whitespace-pre-wrap">{item.detail}</p>
                        <Age at={item.since} className="text-right" />
                    </li>
                ))}
            </ul>
        </Panel>
    )
}
