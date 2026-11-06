import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ApiError } from '@/api/client'
import { epicPlansQuery, epicQuery } from '@/api/queries'
import { NoPlan } from '@/components/epic-board'
import { EpicChangesAsked, EpicPlan, EpicPlanHash, EpicPlanState } from '@/components/epic-plan'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelLoading, PanelSkeleton } from '@/components/panel'
import { epicId, epicTitle } from '@/lib/epics'
import { epicRef } from '@/lib/refs'

// What every epic's plan page shows, on its title's hover: its description is where the plan stands.
const HELP =
    "An epic's plan as its file stands, read only: its newest plan, approved or sent back from its foot while it " +
    "waits on you, then its earlier ones. An epic's plan takes no comments."

/**
 * An epic's plan on a page of its own (DESIGN §43): its newest plan in the plan editor, read only and with no margin,
 * then its earlier plans, folded. The plan wants the page's width, and a page of its own is linked to and left with
 * Back, as a ticket's plan page is; the epic's page leads with the breakdown read from it.
 */
export const Route = createFileRoute('/epics/$id_/plan')({
    component: EpicPlanPage,
})

function EpicPlanPage() {
    const { id } = Route.useParams()
    // An epic's id is a whole number; anything else names no epic, and is never sent to the server as one.
    const number = epicId(id)
    const enabled = number !== undefined
    // The epic for its goal's first line, and for what its page says with no plan; the plans are the page.
    const detail = useQuery({ ...epicQuery(number ?? 0), enabled }).data
    const query = useQuery({ ...epicPlansQuery(number ?? 0), enabled })
    const { data, error } = query
    const header = (
        <PageHeader
            parents={<EpicCrumb id={id} />}
            title="plan"
            subject={detail === undefined ? undefined : epicTitle(detail.epic.text)}
            help={HELP}
            tab={`${epicRef(id)} plan`}
            links={data !== undefined && <EpicPlanHash plans={data} />}
        >
            {data !== undefined && <EpicPlanState epic={data.epic_id} plans={data} />}
        </PageHeader>
    )
    if (number === undefined || (error instanceof ApiError && (error.status === 404 || error.status === 409))) {
        return (
            <>
                {header}
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
                {header}
                <Panel>
                    <PanelLoading query={query} rows={1} className="min-h-72" />
                </Panel>
            </>
        )
    }
    return (
        <>
            {header}
            <EpicChangesAsked plans={data} />
            {data.plans.length > 0 ? (
                // Each epic its own plans, so an earlier plan opened on one is never open on another.
                <EpicPlan key={data.epic_id} epic={data.epic_id} plans={data} />
            ) : (
                <Panel className="max-w-[51rem]" data-testid="epic-plan">
                    {detail === undefined ? <PanelSkeleton rows={1} /> : <NoPlan detail={detail} />}
                </Panel>
            )}
        </>
    )
}

function EpicCrumb({ id }: { id: string }) {
    return (
        <Link to="/epics/$id" params={{ id }} activeOptions={{ exact: true }}>
            {epicRef(id)}
        </Link>
    )
}
