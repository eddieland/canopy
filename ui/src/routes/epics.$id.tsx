import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { FileText } from 'lucide-react'

import { ApiError } from '@/api/client'
import { epicQuery } from '@/api/queries'
import type { EpicDetail } from '@/api/types'
import { Age } from '@/components/age'
import { EpicActions } from '@/components/epic-actions'
import { EpicBoard } from '@/components/epic-board'
import { OutlineLights } from '@/components/epic-ids'
import { OutlinePanel } from '@/components/epic-outline'
import { EpicRunRow } from '@/components/epic-row'
import { EpicStory } from '@/components/epic-story'
import { ListPanel } from '@/components/list-panel'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelLoading, PanelScroll } from '@/components/panel'
import { RowList } from '@/components/rows'
import { Word } from '@/components/status'
import { Button } from '@/components/ui/button'
import { EPIC_LOOK, entriesFiled, epicId, epicTitle } from '@/lib/epics'
import { ordered, useListOrder } from '@/lib/list-order'
import { epicRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { cn } from '@/lib/utils'

// What every epic's page shows, on its title's hover: its description is where the epic stands.
const HELP =
    'An epic you submitted: its breakdown beside the tickets that fulfil it, your goal and its conversation, its ' +
    'requirements and contracts, and its plan runs.'

/**
 * One epic (DESIGN §43), its breakdown first: the board of its plan's entries beside the members that fulfil each,
 * which answers what is left to file; then its story, the goal and what its plan runs and the operator said, beside
 * its requirements and contracts; then its plan runs. Pointing at an id anywhere on it lights the entries that cite it.
 */
export const Route = createFileRoute('/epics/$id')({
    component: EpicPage,
})

function EpicPage() {
    const { id } = Route.useParams()
    // An epic's id is a whole number; anything else names no epic, and is never sent to the server as one.
    const number = epicId(id)
    const query = useQuery({ ...epicQuery(number ?? 0), enabled: number !== undefined })
    const { data, error } = query
    if (number === undefined || (error instanceof ApiError && (error.status === 404 || error.status === 409))) {
        return (
            <>
                <PageHeader title={epicRef(id)} />
                <Panel>
                    {/* An epic canopy has no record of is missing, and says why; a refusal is a Notice. */}
                    {error instanceof ApiError && error.status === 409 ? (
                        <Notice error={error} className="p-3" />
                    ) : (
                        <Empty size="panel">{`canopy has no ${epicRef(id)}`}</Empty>
                    )}
                </Panel>
            </>
        )
    }
    if (data === undefined) {
        return (
            <>
                <PageHeader title={epicRef(number)} />
                <Panel>
                    <PanelLoading query={query} rows={3} className="min-h-72" />
                </Panel>
            </>
        )
    }
    // Each epic its own page, so what one held (a lit id, a thread's scroll) is never another's.
    return <Epic key={data.epic.id} detail={data} />
}

function Epic({ detail }: { detail: EpicDetail }) {
    const { epic, runs } = detail
    const look = EPIC_LOOK[epic.standing]
    const runsOrder = useListOrder('epic-runs')
    const running = runs.find((run) => run.status === 'running')?.id ?? null
    return (
        <>
            <PageHeader
                title={epicRef(epic.id)}
                subject={epicTitle(epic.text)}
                help={HELP}
                controls={
                    <EpicActions
                        epic={epic}
                        running={running}
                        plan={runs.some((run) => run.plan_id !== null) ? <OpenPlan epic={epic.id} /> : undefined}
                    />
                }
            >
                {/* Where it stands first, in its state's color, as a task's page says it. */}
                <Word word={epic.standing} text={look.word} meaning={look.meaning} className={RUN_TEXT[look.state]} />
                {/* Stopped, it says when once; stopped while its plan run still works, it says so after the rest. */}
                {epic.stopped_at !== null && epic.standing === 'stopped' && (
                    <>
                        {' '}
                        <Age at={epic.stopped_at} variant="ago" />
                    </>
                )}
                {` · ${entriesFiled(epic)} · members ${String(detail.members.length)} of at most ` +
                    `${String(detail.bound)} · submitted `}
                <Age at={epic.submitted_at} variant="ago" />
                {epic.stopped_at !== null && epic.standing !== 'stopped' && (
                    <>
                        {' · stopped '}
                        <Age at={epic.stopped_at} variant="ago" />
                    </>
                )}
            </PageHeader>
            <OutlineLights outline={detail.outline}>
                {/* The board first, at the page's width; then the story and the key to the board's ids, which the wide
                    layout sets side by side, and the plan runs under the story. The narrow order is the reading
                    order. */}
                <div className="stagger flex flex-col gap-6">
                    <EpicBoard detail={detail} />
                    <div
                        className={cn(
                            'flex flex-col gap-6',
                            '2xl:grid 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] 2xl:grid-rows-[auto_1fr]',
                            '2xl:items-start',
                        )}
                    >
                        <Panel className="2xl:col-start-1 2xl:row-start-1" data-testid="epic-conversation">
                            <EpicStory detail={detail} />
                        </Panel>
                        <OutlinePanel
                            outline={detail.outline}
                            className="2xl:col-start-2 2xl:row-span-2 2xl:row-start-1"
                        />
                        <ListPanel
                            label="Plan runs"
                            count={runs.length}
                            list="epic-runs"
                            className="2xl:col-start-1 2xl:row-start-2"
                            data-testid="epic-runs"
                        >
                            <PanelScroll label="Plan runs">
                                <RowList kind="own-run" className="divide-y">
                                    {ordered('epic-runs', runsOrder, runs).map((run) => (
                                        <EpicRunRow key={run.id} epic={epic.id} run={run} />
                                    ))}
                                </RowList>
                            </PanelScroll>
                        </ListPanel>
                    </div>
                </div>
            </OutlineLights>
        </>
    )
}

// The plan's own page, where its text has the page's width, once any plan run recorded one.
function OpenPlan({ epic }: { epic: number }) {
    return (
        <Button asChild variant="outline" size="sm">
            <Link to="/epics/$id/plan" params={{ id: String(epic) }}>
                <FileText />
                Open plan
            </Link>
        </Button>
    )
}
