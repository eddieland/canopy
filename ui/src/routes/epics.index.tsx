import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { epicsQuery } from '@/api/queries'
import { Code } from '@/components/code'
import { EpicRow } from '@/components/epic-row'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { RowList } from '@/components/rows'
import { counted } from '@/lib/descriptions'

/** Every epic the operator submitted, the newest first, each with where its plan stands and how much of it is filed. */
export const Route = createFileRoute('/epics/')({
    component: EpicsPage,
})

function EpicsPage() {
    const query = useQuery(epicsQuery)
    const { data } = query
    return (
        <>
            <PageHeader title="Epics">
                Work that spans several tickets, toward one goal in your own words. A planner reads its repositories and
                proposes one plan for the whole, which you approve once; its breakdown says which tickets to file, and
                each ticket you add as a member is planned against it. Being a member authorizes no work on a ticket.
            </PageHeader>
            <Panel>
                <PanelHeader label="Epics">
                    {data !== undefined && (
                        <span className="readout text-xs text-muted-foreground" data-testid="epics-count">
                            {counted(data.length, 'epic')}
                        </span>
                    )}
                </PanelHeader>
                {data === undefined ? (
                    <PanelLoading query={query} className="min-h-72" />
                ) : data.length === 0 ? (
                    <Empty size="panel">
                        no epics yet: <Code>canopy epic submit TEXT</Code> hands canopy one
                    </Empty>
                ) : (
                    <RowList kind="epic" className="divide-y" data-testid="epics">
                        {data.map((epic) => (
                            <EpicRow key={epic.id} epic={epic} />
                        ))}
                    </RowList>
                )}
            </Panel>
        </>
    )
}
