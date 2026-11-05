import { useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { useState } from 'react'

import { approveEpicPlan, newSubmission, replyEpic } from '@/api/mutations'
import { keys } from '@/api/queries'
import type { EpicPlanFile, EpicPlans } from '@/api/types'
import { Age } from '@/components/age'
import { ApprovedBand } from '@/components/approved-band'
import { Copyable } from '@/components/copy-button'
import { Disclosure } from '@/components/disclosure'
import { Notice } from '@/components/notice'
import { Empty, Panel, PanelHeader } from '@/components/panel'
import { ChangesAskedBand } from '@/components/plan-card'
import { PlanEditor } from '@/components/plan-editor'
import { Chip } from '@/components/status'
import { Tip } from '@/components/tip'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { epicApprovedText, epicRepliedText } from '@/lib/outcomes'
import { epicRunRef } from '@/lib/refs'

// How much of a plan's hash its page shows: enough to tell two apart at a glance, the whole on hover and copied whole.
const HASH_SHOWN = 12
// What Approve does, on its hover.
const APPROVE_TITLE =
    "Approving takes the plan as its file stands, by the hash under the title; its members' planners plan " +
    'against it.'

/**
 * An epic's plans (DESIGN §43), on their page: the newest in the plan editor, read only and with no margin, since an
 * epic's plan takes no comments, what changed since the plan it replaces marked on it while it waits on the operator,
 * with Approve and Ask for changes then; then its earlier plans, newest first, each folded until opened, read only too.
 * Every plan is the planner's text, which the editor's schema keeps as text. `epic` is the epic's id; `plans` hold at
 * least one plan.
 */
export function EpicPlan({ epic, plans }: { epic: number; plans: EpicPlans }) {
    const newest = plans.plans.at(-1)
    if (newest === undefined) {
        return null
    }
    const earlier = plans.plans.slice(0, -1).toReversed()
    return (
        <section aria-label="Plan" className="flex flex-col gap-3" data-testid="epic-plan">
            {newest.text === null ? (
                <Panel className="max-w-[51rem]">
                    <Empty size="panel">
                        plan {newest.plan.id}&apos;s file is {newest.problem ?? 'unreadable'}: {newest.path}
                    </Empty>
                </Panel>
            ) : (
                // Its own plan's: what the operator's word on one plan did is never said on the next.
                <NewestPlan key={newest.plan.id} epic={epic} plans={plans} newest={newest} text={newest.text} />
            )}
            {earlier.length > 0 && <EarlierPlans epic={epic} plans={earlier} />}
        </section>
    )
}

/**
 * The newest plan in the editor, with the operator's word on it while it waits on them: Approve, by the file's hash as
 * the page read it, which canopy refuses (`stale`) once the file changed since; and Ask for changes, a reply its next
 * plan run reads. Each says what it did in the CLI's words, or names the guard that refused it, at the plan's foot.
 */
function NewestPlan({
    epic,
    plans,
    newest,
    text,
}: {
    epic: number
    plans: EpicPlans
    newest: EpicPlanFile
    text: string
}) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const [failure, setFailure] = useState<unknown>(null)
    const [busy, setBusy] = useState(false)
    // How many times the operator approved the plan here, the last thing they did: each plays its moment once.
    const [approvals, setApprovals] = useState(0)
    const [approved, setApproved] = useState(false)
    const before = plans.plans.at(-2)
    const waits = planWaits(plans, newest)

    // `work` says what it did; the epic and its plans are read again once it ends, done or refused.
    async function act(work: () => Promise<string>, approving: boolean): Promise<void> {
        setFailure(null)
        setSaid(null)
        setApproved(false)
        setBusy(true)
        try {
            setSaid(await work())
            // Only once the journal holds it: the moment never shows for an approval that was refused.
            if (approving) {
                setApproved(true)
                setApprovals((n) => n + 1)
            }
        } catch (error: unknown) {
            setFailure(error)
        } finally {
            setBusy(false)
            // No stream event carries an epic: its page and the list read it again.
            void client.invalidateQueries({ queryKey: keys.epic(epic) })
            void client.invalidateQueries({ queryKey: keys.epics })
        }
    }

    function approve() {
        const read = newest.sha256 ?? ''
        void act(async () => epicApprovedText(epic, await approveEpicPlan(epic, read)), true)
    }

    function askForChanges(message: string) {
        void act(async () => epicRepliedText(epic, await replyEpic(epic, message, newSubmission())), false)
    }

    return (
        <PlanEditor
            // A new file is a new editor, so what Approve takes is always what the page shows: the editor reads its
            // Markdown once, and an approval names the hash it was read by.
            key={newest.sha256}
            markdown={text}
            threads={[]}
            onThreadsChange={ignore}
            editable={false}
            comments={false}
            decides={waits}
            previous={
                before?.text === null || before?.text === undefined
                    ? undefined
                    : { label: `plan ${before.plan.id}`, markdown: before.text, shown: waits }
            }
            status={
                <>
                    <EpicPlanChip file={newest} waits={waits} asked={plans.changes_asked !== null} />
                    <Age at={newest.plan.created_at} variant="ago" />
                </>
            }
            onAskForChanges={waits ? askForChanges : undefined}
            asked={plans.changes_asked !== null}
            renderActions={(notes) => (
                // `contents`, so its items are the foot's line's, with Ask for changes after them.
                <div className="contents" data-testid="plan-actions">
                    <Button
                        onClick={approve}
                        // A note on the whole plan goes only with Ask for changes: approving would leave it unsent.
                        disabled={busy || notes !== ''}
                        title={notes === '' ? APPROVE_TITLE : 'An approval sends no note: ask for changes with it.'}
                    >
                        <Check />
                        Approve
                    </Button>
                </div>
            )}
            // Kept once the plan no longer waits, so the approval that ended its waiting still says what it did.
            outcome={
                approved && said !== null && failure === null ? (
                    <ApprovedBand key={approvals} text={said} />
                ) : said !== null || failure !== null ? (
                    <Notice error={failure}>{said}</Notice>
                ) : undefined
            }
        />
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
            {planWaits(plans, newest) &&
                plans.changes_asked === null &&
                ' It waits on you: approve it, or ask for changes.'}
        </>
    )
}

// Whether the newest plan waits on the operator: proposed, and no plan run at work on the next.
function planWaits(plans: EpicPlans, newest: EpicPlanFile): boolean {
    return newest.plan.status === 'proposed' && plans.planning === null
}

/**
 * Where a plan stands, as a chip: `waiting on you` in the blocked tone while it waits on the operator, as everything
 * that waits on them reads, or `changes asked` in the running tone once they asked and the loop acts next, as a
 * ticket's plan says it; else its status.
 */
function EpicPlanChip({ file, waits, asked }: { file: EpicPlanFile; waits: boolean; asked: boolean }) {
    if (!waits) {
        return <Chip>{file.plan.status}</Chip>
    }
    return asked ? <Chip tone="running">changes asked</Chip> : <Chip tone="blocked">waiting on you</Chip>
}

/**
 * The band under an epic's plan page's header while the operator's request for changes waits on the next tick's plan
 * run, as a ticket's plan page has (`ChangesAsked`). Nothing otherwise, a plan run at work on it included.
 */
export function EpicChangesAsked({ plans }: { plans: EpicPlans }) {
    if (plans.changes_asked === null || plans.planning !== null) {
        return null
    }
    return (
        <ChangesAskedBand at={plans.changes_asked}>
            the next tick starts its next plan run, which reads your reply.
        </ChangesAskedBand>
    )
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
