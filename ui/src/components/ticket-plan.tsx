import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useBlocker } from '@tanstack/react-router'
import { Check, Save, SkipForward } from 'lucide-react'
import { useEffect, useEffectEvent, useRef, useState } from 'react'

import {
    changePlanThread,
    commentPlan,
    decidePlan,
    deletePlanThread,
    newSubmission,
    replyPlanThread,
    replyTicket,
    savePlan,
} from '@/api/mutations'
import { keys, ticketPlanQuery } from '@/api/queries'
import type { PlanChanged, PlanFile, PlanSummary, TicketPlans } from '@/api/types'
import { Age } from '@/components/age'
import { Disclosure } from '@/components/disclosure'
import { Notice } from '@/components/notice'
import { Empty, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { PlanEditor } from '@/components/plan-editor'
import { Chip } from '@/components/status'
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { PendingWork, usePending, usePendingWork } from '@/hooks/use-pending'
import { planText } from '@/lib/outcomes'
import { fromServer, movedAnchors, threadChanges } from '@/lib/plan-threads'
import type { PlanThread, ThreadChange } from '@/lib/plan-threads'
import { isApple } from '@/lib/send-key'
import { ariaKeys, isPressed, keysLabel } from '@/lib/shortcut'

const APPLE = isApple(navigator.userAgent)
// Save, as a document's: anywhere on the page while the plan is open.
const SAVE_KEYS = 'Mod-s'

/**
 * A ticket's plan (docs/design/PLANNING.md §25): its newest plan in the plan editor, where the operator edits it and
 * comments on its passages, with Approve, Ask for changes, and Skip; then its earlier plans, each read only. Every
 * write goes through the CLI's code: approve and skip are `canopy plan`'s, asking for changes is a reply, and a save
 * writes the plan's file as the operator's own editor would, refused if the file changed since it was read. Comments
 * are saved as they are made; a passage an edit moved is saved with the plan.
 */
export function TicketPlan({ ticketKey, plans }: { ticketKey: string; plans: TicketPlans }) {
    const newest = plans.newest
    const earlier = plans.plans.filter((plan) => plan.id !== newest?.plan.id).toReversed()
    // What leaving the page would lose, which it asks about first: an edit not yet saved, or words not yet sent.
    const [pending, reportPending] = usePendingWork()
    const held = new Set(pending.values())
    const leaving = useBlocker({
        // A move within the page, such as a list flipped, loses nothing.
        shouldBlockFn: ({ current, next }) => current.pathname !== next.pathname,
        enableBeforeUnload: true,
        disabled: pending.size === 0,
        withResolver: true,
    })
    return (
        <section aria-label="Plan" className="flex flex-col gap-3" data-testid="ticket-plan">
            <PlanStatus plans={plans} />
            {newest !== null && newest.text !== null && (
                <PendingWork value={reportPending}>
                    <NewestPlan
                        key={newest.plan.id}
                        ticketKey={ticketKey}
                        plans={plans}
                        newest={newest}
                        text={newest.text}
                    />
                </PendingWork>
            )}
            {newest !== null && newest.text === null && (
                <Panel>
                    <Empty size="panel">
                        plan {newest.plan.id}&apos;s file is {newest.problem ?? 'unreadable'}: {newest.path}
                    </Empty>
                </Panel>
            )}
            {earlier.length > 0 && <EarlierPlans ticketKey={ticketKey} plans={earlier} />}
            <ConfirmLeave
                open={leaving.status === 'blocked'}
                edits={held.has('edit')}
                words={held.has('words')}
                onStay={() => leaving.reset?.()}
                onLeave={() => leaving.proceed?.()}
            />
        </section>
    )
}

/** Whether the ticket needs a plan and why, its newest plan's status and approval, and a planner at work. */
function PlanStatus({ plans }: { plans: TicketPlans }) {
    const newest = plans.newest
    const why = plans.setting === null ? `policy.plan ${plans.policy}` : `your word, ${plans.setting}`
    return (
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" data-testid="plan-status">
            <span>
                Plan {plans.needed ? 'needed' : 'not needed'}, by {why}.
            </span>
            {newest !== null && (
                <span className="flex items-center gap-1.5">
                    <Chip>{newest.plan.status}</Chip>
                    plan {newest.plan.id}, written <Age at={newest.plan.created_at} variant="ago" />
                    {newest.plan.approved_at !== null && (
                        <>
                            , approved <Age at={newest.plan.approved_at} variant="ago" /> via{' '}
                            {newest.plan.approved_channel}
                        </>
                    )}
                    {newest.edited && <span>, edited since the planner wrote it</span>}
                    {newest.changed_since_approval && <span>, changed since it was approved</span>}
                </span>
            )}
            {newest === null && plans.planning === null && plans.needed && (
                <span>None yet: the next tick dispatches a planner.</span>
            )}
            {plans.planning !== null && <span>Run {plans.planning} is writing a new plan.</span>}
            {plans.planning === null && plans.changes_asked !== null && (
                <span>
                    You asked for changes <Age at={plans.changes_asked} variant="ago" />: the next tick asks the planner
                    for a new plan.
                </span>
            )}
        </p>
    )
}

/**
 * The newest plan in the editor, and the operator's word on it. Its threads are the journal's, held here as the
 * editor changes them and written as each change is made, one after another, so a reply to a comment just made waits
 * for the comment.
 */
function NewestPlan({
    ticketKey,
    plans,
    newest,
    text,
}: {
    ticketKey: string
    plans: TicketPlans
    newest: PlanFile
    text: string
}) {
    const client = useQueryClient()
    // The plan this one replaces, the newest before it, for what changed since.
    const before = plans.plans.findLast(
        (plan) => plan.id !== newest.plan.id && plan.created_at <= newest.plan.created_at,
    )
    const replaced = useQuery({ ...ticketPlanQuery(ticketKey, before?.id ?? 0), enabled: before !== undefined }).data
    const saved = fromServer(plans.threads)
    const [held, setHeld] = useState(saved)
    const [seen, setSeen] = useState(plans.threads)
    const [markdown, setMarkdown] = useState(text)
    const [said, setSaid] = useState<string | null>(null)
    const [failure, setFailure] = useState<unknown>(null)
    const [busy, setBusy] = useState(0)
    // A comment made here has a local id until the journal gives it one: later changes to it wait for that.
    const created = useRef(new Map<string, Promise<number>>())
    const queue = useRef<Promise<unknown>>(Promise.resolve())
    if (seen !== plans.threads && busy === 0) {
        // The journal's threads, read again: they replace what is held, but for passages an unsaved edit moved.
        setSeen(plans.threads)
        const moved = new Map(movedAnchors(fromServer(seen), held).map((thread) => [thread.id, thread.anchor]))
        setHeld(saved.map((thread) => Object.assign(thread, { anchor: moved.get(thread.id) ?? thread.anchor })))
    }
    const status = newest.plan.status
    const editable = plans.planning === null && (status === 'proposed' || status === 'approved')
    const dirty = markdown !== text
    usePending(dirty, 'edit')
    const approvable = status === 'proposed' || (status === 'approved' && (newest.changed_since_approval || dirty))

    function refresh(): Promise<void> {
        return client.invalidateQueries({ queryKey: keys.ticketPlans(ticketKey) })
    }

    // Runs `work` after every write before it, and reads the plans again once the last one ends.
    function enqueue(work: () => Promise<unknown>) {
        setBusy((n) => n + 1)
        const next = queue.current.then(work).catch((error: unknown) => setFailure(error))
        queue.current = next
        // Busy until the plans are read again: a save before then would send the hash of the file as it was.
        void next.then(refresh).finally(() => setBusy((n) => n - 1))
    }

    async function serverId(id: string): Promise<number> {
        return (await created.current.get(id)) ?? Number(id)
    }

    async function write(change: ThreadChange): Promise<unknown> {
        switch (change.kind) {
            case 'add': {
                const made = commentPlan(ticketKey, change.thread.anchor, change.thread.body).then((t) => t.id)
                created.current.set(change.thread.id, made)
                return made
            }
            case 'delete': {
                return deletePlanThread(ticketKey, await serverId(change.id))
            }
            case 'edit': {
                return changePlanThread(ticketKey, await serverId(change.id), { body: change.body })
            }
            case 'resolve': {
                return changePlanThread(ticketKey, await serverId(change.id), { resolved: change.resolved })
            }
            case 'reply': {
                return replyPlanThread(ticketKey, await serverId(change.id), change.body)
            }
            case 'edit-reply': {
                return changePlanThread(ticketKey, await serverId(change.id), {
                    body: change.body,
                    reply: Number(change.replyId),
                })
            }
        }
    }

    function onThreadsChange(next: PlanThread[]) {
        const changes = threadChanges(held, next)
        setHeld(next)
        setFailure(null)
        for (const change of changes) {
            enqueue(() => write(change))
        }
    }

    // The edit over the plan's file, then each passage it moved, so a comment stays on its words in the journal too.
    async function save(): Promise<void> {
        await savePlan(ticketKey, newest.plan.id, markdown, newest.sha256 ?? '')
        const moved = movedAnchors(fromServer(plans.threads), held)
        await Promise.all(
            moved.map(async (thread) =>
                changePlanThread(ticketKey, await serverId(thread.id), { anchor: thread.anchor }),
            ),
        )
    }

    async function saveAndSay(): Promise<string> {
        await save()
        return 'Saved the plan.'
    }

    function act(work: () => Promise<string>) {
        setFailure(null)
        setSaid(null)
        enqueue(async () => setSaid(await work()))
    }

    const onSaveKey = useEffectEvent((event: KeyboardEvent) => {
        if (!isPressed(SAVE_KEYS, event, APPLE)) {
            return
        }
        // Never the browser's own Save, which would keep a copy of the page rather than save the plan.
        event.preventDefault()
        if (dirty && busy === 0) {
            act(saveAndSay)
        }
    })
    useEffect(() => {
        const listener = (event: KeyboardEvent) => onSaveKey(event)
        document.addEventListener('keydown', listener)
        return () => document.removeEventListener('keydown', listener)
    }, [])

    function decide(action: PlanChanged['action']) {
        act(async () => {
            if (dirty && action === 'approve') {
                await save()
            }
            return planText(ticketKey, await decidePlan(ticketKey, action))
        })
    }

    function askForChanges(message: string) {
        act(async () => {
            // The planner reads the plan's file: an edit only in the editor would not reach it, and the new plan
            // would replace it unseen.
            if (dirty) {
                await save()
            }
            const replied = await replyTicket(ticketKey, message, newSubmission())
            void client.invalidateQueries({ queryKey: keys.ticket(ticketKey) })
            return (
                `Recorded message ${replied.message_id} on ${ticketKey}: the next tick asks the planner for a new ` +
                'plan with your comments.'
            )
        })
    }

    return (
        <PlanEditor
            markdown={text}
            threads={held}
            onThreadsChange={onThreadsChange}
            onChange={setMarkdown}
            editable={editable}
            edited={newest.edited}
            previous={
                before !== undefined && typeof replaced?.text === 'string'
                    ? { label: `plan ${before.id}`, markdown: replaced.text }
                    : undefined
            }
            onAskForChanges={status === 'proposed' ? askForChanges : undefined}
            asked={plans.changes_asked !== null}
            actions={
                <div className="flex flex-wrap items-center gap-2" data-testid="plan-actions">
                    {approvable && (
                        <Button onClick={() => decide('approve')} disabled={busy > 0}>
                            <Check />
                            {dirty ? 'Save and approve' : 'Approve'}
                        </Button>
                    )}
                    <Button
                        variant="outline"
                        onClick={() => act(saveAndSay)}
                        disabled={busy > 0 || !dirty}
                        title={`Save (${keysLabel(SAVE_KEYS, APPLE)})`}
                        aria-keyshortcuts={ariaKeys(SAVE_KEYS, APPLE)}
                    >
                        <Save />
                        Save
                    </Button>
                    {dirty && (
                        // As a document says it, so an edit not yet in the plan's file is never taken for one that is.
                        <span className="text-xs text-muted-foreground">Unsaved edits</span>
                    )}
                    <Button variant="ghost" onClick={() => decide('skip')} disabled={busy > 0}>
                        <SkipForward />
                        Skip the plan
                    </Button>
                </div>
            }
            actionsNote={
                <div className="flex flex-col gap-2">
                    <p className="text-xs text-muted-foreground">
                        Approving takes the plan as saved, your edits included, and lets its implement go ahead.
                        {status === 'approved' && ' Saving an edit means approving it again.'}
                    </p>
                    <Notice error={failure}>{said}</Notice>
                </div>
            }
        />
    )
}

/** The ticket's earlier plans, newest first, each read only once opened. */
function EarlierPlans({ ticketKey, plans }: { ticketKey: string; plans: PlanSummary[] }) {
    return (
        <Panel data-testid="earlier-plans">
            <PanelHeader label="Earlier plans">
                <span className="readout text-xs text-muted-foreground">{plans.length}</span>
            </PanelHeader>
            <ul className="flex flex-col divide-y">
                {plans.map((plan) => (
                    <EarlierPlan key={plan.id} ticketKey={ticketKey} plan={plan} />
                ))}
            </ul>
        </Panel>
    )
}

function EarlierPlan({ ticketKey, plan }: { ticketKey: string; plan: PlanSummary }) {
    const [open, setOpen] = useState(false)
    const found = useQuery({ ...ticketPlanQuery(ticketKey, plan.id), enabled: open }).data
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <li className="flex flex-col">
                <div className="flex items-center gap-2 px-3 py-2 text-sm">
                    <Disclosure open={open} what={`plan ${plan.id}`} />
                    <span>plan {plan.id}</span>
                    <Chip>{plan.status}</Chip>
                    <span className="text-muted-foreground">
                        written <Age at={plan.created_at} variant="ago" />
                    </span>
                </div>
                <CollapsibleContent>
                    {found === undefined && <PanelSkeleton rows={3} />}
                    {found !== undefined && found.text === null && (
                        <Empty>its file is {found.problem ?? 'unreadable'}</Empty>
                    )}
                    {found !== undefined && found.text !== null && (
                        <div className="p-3">
                            <PlanEditor markdown={found.text} threads={[]} onThreadsChange={ignore} editable={false} />
                        </div>
                    )}
                </CollapsibleContent>
            </li>
        </Collapsible>
    )
}

// An earlier plan is read only: nothing changes its threads.
function ignore(): void {
    // Nothing to do.
}

// Leaving the page with an edit not yet saved, or words in a comment not yet sent, asks first, as a document does:
// Stay, which takes the focus and which Escape gives too, or Leave, which loses them.
function ConfirmLeave({
    open,
    edits,
    words,
    onStay,
    onLeave,
}: {
    open: boolean
    edits: boolean
    words: boolean
    onStay: () => void
    onLeave: () => void
}) {
    const lost = [edits && 'your edits to the plan are not saved', words && 'what you wrote in a comment is not sent']
    return (
        <AlertDialog
            open={open}
            onOpenChange={(next) => {
                if (!next) {
                    onStay()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogTitle>Leave this page?</AlertDialogTitle>
                <AlertDialogDescription>{leaveText(lost.filter((part) => part !== false))}</AlertDialogDescription>
                <AlertDialogFooter>
                    <AlertDialogCancel>Stay</AlertDialogCancel>
                    <AlertDialogAction onClick={onLeave}>Leave</AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}

// What leaving loses, as a sentence: `Your edits to the plan are not saved, and what you wrote ... is not sent.`
function leaveText(parts: string[]): string {
    const said = parts.join(', and ')
    return `${said.charAt(0).toUpperCase()}${said.slice(1)}.`
}
