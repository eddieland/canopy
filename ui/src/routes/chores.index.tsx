import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { choresQuery } from '@/api/queries'
import type { ChoreSummary } from '@/api/types'
import { ChoreLink } from '@/components/chore-link'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { RunDot } from '@/components/status'
import { Skeleton } from '@/components/ui/skeleton'
import { choreLine, windowText } from '@/lib/chores'
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
            <PageHeader label="Recurring" title="Chores">
                Each configured chore, as <code className="font-mono text-xs">canopy status</code> lists it. The
                overseer decides when one runs; a note tells its next runs what to leave out or look at.
            </PageHeader>
            <Panel>
                <PanelHeader label="Chores">
                    <span className="readout text-xs text-muted-foreground">{data?.length ?? ''}</span>
                </PanelHeader>
                {data === undefined ? (
                    <div className="flex min-h-40 flex-col gap-2 p-3">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-4 w-1/2" />
                    </div>
                ) : data.length === 0 ? (
                    <Placeholder className="min-h-40">
                        no chores run here: define [chores.NAME] in your user config, with capacity.max_chores above 0
                    </Placeholder>
                ) : (
                    <ul className="stagger divide-y" data-testid="chores">
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
    const findings = chore.findings.length
    return (
        <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`chore-${chore.name}`}>
            <div className="flex items-center gap-3">
                <ChoreLink name={chore.name} className="w-40 truncate" />
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
                    className={cn(
                        'ml-auto font-mono text-xs',
                        findings > 0 ? 'text-foreground' : 'text-muted-foreground',
                    )}
                    data-testid="chore-findings"
                >
                    {findings === 1 ? '1 open finding' : `${findings} open findings`}
                </span>
            </div>
            <p className="pl-[11.75rem] font-mono text-xs text-muted-foreground">
                at most every {chore.every_minutes}m · {windowText(chore)}
            </p>
        </li>
    )
}
