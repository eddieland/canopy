import { useState } from 'react'

import type { EpicPlanFile, EpicPlans } from '@/api/types'
import { Age } from '@/components/age'
import { Code } from '@/components/code'
import { Copyable } from '@/components/copy-button'
import { Disclosure } from '@/components/disclosure'
import { Empty, Panel, PanelHeader } from '@/components/panel'
import { PlanEditor } from '@/components/plan-editor'
import { Chip } from '@/components/status'
import { Tip } from '@/components/tip'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { epicRef, epicRunRef } from '@/lib/refs'

// How much of a plan's hash its page shows: enough to tell two apart at a glance, the whole on hover and copied whole.
const HASH_SHOWN = 12

/**
 * An epic's plans (DESIGN §43), on their page: the newest in the plan editor, read only and with no margin, since an
 * epic's plan takes no comments, what changed since the plan it replaces marked on it while it waits on the operator;
 * then its earlier plans, newest first, each folded until opened, read only too. Every plan is the planner's text,
 * which the editor's schema keeps as text. `epic` is the epic's id; `plans` hold at least one plan.
 */
export function EpicPlan({ epic, plans }: { epic: number; plans: EpicPlans }) {
    const newest = plans.plans.at(-1)
    if (newest === undefined) {
        return null
    }
    const earlier = plans.plans.slice(0, -1).toReversed()
    // The plan this one replaces, for what changed since, while its file reads.
    const before = earlier[0]
    const waits = planWaits(plans, newest)
    return (
        <section aria-label="Plan" className="flex flex-col gap-3" data-testid="epic-plan">
            {newest.text === null ? (
                <Panel className="max-w-[51rem]">
                    <Empty size="panel">
                        plan {newest.plan.id}&apos;s file is {newest.problem ?? 'unreadable'}: {newest.path}
                    </Empty>
                </Panel>
            ) : (
                <PlanEditor
                    // A new plan is a new editor: the editor reads its Markdown once.
                    key={newest.plan.id}
                    markdown={newest.text}
                    threads={[]}
                    onThreadsChange={ignore}
                    editable={false}
                    comments={false}
                    previous={
                        before?.text === null || before?.text === undefined
                            ? undefined
                            : { label: `plan ${before.plan.id}`, markdown: before.text, shown: waits }
                    }
                    status={
                        <>
                            <EpicPlanChip file={newest} waits={waits} />
                            <Age at={newest.plan.created_at} variant="ago" />
                        </>
                    }
                />
            )}
            {earlier.length > 0 && <EarlierPlans epic={epic} plans={earlier} />}
        </section>
    )
}

/**
 * The newest plan's state in a sentence or two, its page's description: the plan run that wrote it, its approval, what
 * changed in its file since, and what comes next. Its status and age are its panel's header, and its hash the line
 * under this one (`EpicPlanHash`). With no plan, it says nothing: the page's panel says what comes.
 */
export function EpicPlanState({ epic, plans }: { epic: number; plans: EpicPlans }) {
    const newest = plans.plans.at(-1)
    if (newest === undefined) {
        return null
    }
    const { plan } = newest
    return (
        <>
            Written by <span className="readout text-xs">{epicRunRef(epic, plan.run_id)}</span>
            {plan.approved_at !== null && (
                <>
                    , approved <Age at={plan.approved_at} variant="ago" className="text-sm" /> via{' '}
                    {plan.approved_channel}
                </>
            )}
            {newest.edited && ', edited since the planner wrote it'}
            {newest.changed_since_approval && ', changed since you approved it: canopy reads the copy you approved'}.
            {plans.planning !== null && (
                <>
                    {' '}
                    <span className="readout text-xs">{epicRunRef(epic, plans.planning)}</span> is writing a new plan.
                </>
            )}
            {planWaits(plans, newest) && (
                <>
                    {' '}
                    It waits on you: <Code>canopy plan {epicRef(epic)} --approve</Code> approves it, and{' '}
                    <Code>canopy reply {epicRef(epic)}</Code> asks for changes.
                </>
            )}
        </>
    )
}

// Whether the newest plan waits on the operator: proposed, and no plan run at work on the next.
function planWaits(plans: EpicPlans, newest: EpicPlanFile): boolean {
    return newest.plan.status === 'proposed' && plans.planning === null
}

/**
 * Where a plan stands, as a chip: `waiting on you` in the blocked tone while it waits on the operator, as everything
 * that waits on them reads; else its status.
 */
function EpicPlanChip({ file, waits }: { file: EpicPlanFile; waits: boolean }) {
    return waits ? <Chip tone="blocked">waiting on you</Chip> : <Chip>{file.plan.status}</Chip>
}

/**
 * The newest plan's file's SHA-256 as it stands, the hash canopy approves it by, as a readout under its page's
 * description: its first characters, the whole on hover and copied whole. Nothing while the file does not read.
 */
export function EpicPlanHash({ plans }: { plans: EpicPlans }) {
    const sha256 = plans.plans.at(-1)?.sha256
    if (sha256 === null || sha256 === undefined) {
        return null
    }
    return (
        <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground" data-testid="plan-hash">
            <span className="panel-label">sha256</span>
            <Copyable text={sha256} label="plan hash">
                <Tip fact={sha256} mono>
                    <span className="readout">{sha256.slice(0, HASH_SHOWN)}</span>
                </Tip>
            </Copyable>
        </p>
    )
}

/** The epic's earlier plans, newest first, each read only once opened. */
function EarlierPlans({ epic, plans }: { epic: number; plans: EpicPlanFile[] }) {
    return (
        // As wide as the plan above it: its plans read in the plan's measure.
        <Panel data-testid="earlier-plans" className="max-w-[51rem]">
            <PanelHeader label="Earlier plans">
                <span className="readout text-xs text-muted-foreground">{plans.length}</span>
            </PanelHeader>
            <ul className="flex flex-col divide-y">
                {plans.map((file) => (
                    <EarlierPlan key={file.plan.id} epic={epic} file={file} />
                ))}
            </ul>
        </Panel>
    )
}

function EarlierPlan({ epic, file }: { epic: number; file: EpicPlanFile }) {
    const [open, setOpen] = useState(false)
    const { plan } = file
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <li className="flex flex-col">
                <div className="flex items-center gap-2 px-3 py-2 text-sm">
                    <Disclosure open={open} what={`plan ${plan.id}`} />
                    <Chip>{plan.status}</Chip>
                    <span className="text-muted-foreground">
                        written by <span className="readout text-xs">{epicRunRef(epic, plan.run_id)}</span>{' '}
                        <Age at={plan.created_at} variant="ago" />
                    </span>
                </div>
                <CollapsibleContent>
                    {file.text === null ? (
                        <Empty>its file is {file.problem ?? 'unreadable'}</Empty>
                    ) : (
                        <div className="p-3">
                            <PlanEditor
                                markdown={file.text}
                                threads={[]}
                                onThreadsChange={ignore}
                                editable={false}
                                comments={false}
                            />
                        </div>
                    )}
                </CollapsibleContent>
            </li>
        </Collapsible>
    )
}

// An epic's plan takes no comments: nothing changes its threads.
function ignore(): void {
    // Nothing to do.
}
