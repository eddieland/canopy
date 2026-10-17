import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { choresQuery } from '@/api/queries'
import type { ChoreSummary } from '@/api/types'
import { ChoreLink } from '@/components/chore-link'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { ListRow, RowLine } from '@/components/rows'
import { RunDot } from '@/components/status'
import { cadenceText, choreLine, findingsText, windowText } from '@/lib/chores'
import { costText } from '@/lib/cost-total'
import { RUN_TEXT } from '@/lib/run-state'
import { useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/** Each configured chore, as `canopy status` lists it. */
export const Route = createFileRoute('/chores/')({
    component: ChoresPage,
})

function ChoresPage() {
    const { data } = useQuery(choresQuery)
    return (
        <>
            <PageHeader title="Chores">
                Each configured chore, as <code className="font-mono text-xs">canopy status</code> lists it. The
                overseer decides when one runs; a note tells its next runs what to leave out or look at.
            </PageHeader>
            <Panel>
                <PanelHeader label="Chores">
                    <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelSkeleton className="min-h-40" />
                ) : data.length === 0 ? (
                    <Empty size="panel">
                        no chores yet: define [chores.NAME] in your user config, with capacity.max_chores above 0
                    </Empty>
                ) : (
                    <ul className="divide-y" data-testid="chores">
                        {data.map((chore) => (
                            <Row key={chore.name} chore={chore} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

function Row({ chore }: { chore: ChoreSummary }) {
    const now = useNow()
    const run = chore.running ?? chore.latest
    const waiting = chore.findings.some((f) => !f.dismissed)
    return (
        <ListRow kind="chore" data-testid={`chore-${chore.name}`}>
            <ChoreLink name={chore.name} className="truncate" />
            <span
                className={cn(
                    'flex items-center gap-1.5 font-mono text-xs',
                    run ? RUN_TEXT[run.state] : 'text-muted-foreground',
                )}
            >
                {run && <RunDot state={run.state} />}
                {choreLine(chore, now)}
            </span>
            <span
                className={cn('text-right font-mono text-xs', waiting ? 'text-foreground' : 'text-muted-foreground')}
                data-testid="chore-findings"
            >
                {findingsText(chore.findings)}
            </span>
            <RowLine
                from="state"
                className="flex flex-wrap items-center gap-x-3 font-mono text-xs text-muted-foreground"
            >
                <span>
                    at most {cadenceText(chore.every_minutes)} · {windowText(chore)}
                </span>
                <span
                    className="readout ml-auto"
                    title="what its runs cost in the last 24 hours and the last 30 days"
                    data-testid="chore-spend"
                >
                    {costText(chore.spend.day.cost_usd)} 24h · {costText(chore.spend.month.cost_usd)} 30d
                </span>
            </RowLine>
        </ListRow>
    )
}
