import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { useId, useState } from 'react'
import type { SubmitEvent } from 'react'

import { approveFeedbackPlan, refreshTicket } from '@/api/mutations'
import type { FeedbackPlan, FeedbackPlanItem, FeedbackPlanStatus } from '@/api/types'
import { Age } from '@/components/age'
import { Disclosure } from '@/components/disclosure'
import { Textarea } from '@/components/input'
import { MemoryText } from '@/components/memory-text'
import { Notice } from '@/components/notice'
import { Panel, PanelFooter, PanelHeader } from '@/components/panel'
import { RunLink } from '@/components/run-link'
import { SendKeycap } from '@/components/send-keycap'
import { Chip } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { feedbackPlanApprovedText } from '@/lib/outcomes'
import { useSendKeys } from '@/lib/send-key'
import type { Tone } from '@/lib/tone'

// A plan's status in its chip's color: one waiting on the operator, stale or not, as a waiting draft is; an approved
// one as what the loop is about to act on; a spent one plain.
const STATUS_TONE: Record<FeedbackPlanStatus, Tone> = {
    waiting: 'blocked',
    stale: 'blocked',
    approved: 'running',
    spent: 'plain',
}
// What approving a stale plan does: refused once, naming what changed, then approved as it is.
const REFUSED_ONCE =
    'The loop plans it again once the PR goes quiet. Approving it now is refused once, naming this; approving it ' +
    'again approves it as it is.'
const AGAIN = 'Approving it again approves it as it is; what changed waits for the next plan.'
// The line beside the approve button, with an item ticked and with none.
const WRITES =
    'Approving writes a message on the ticket naming the items to address and to leave, by number, with your words ' +
    'after it.'
const NONE_TICKED = 'Tick an item to approve, or reply on the ticket to ask for changes.'

/**
 * The current feedback plan of the PR's ticket (DESIGN §32): where it stands, what changed on its PRs since it was
 * written while it is stale, each item it covers in a row, its number, what it proposes, its author and whether they
 * are trusted, and where it is, with the reply it would draft for one no thread card on the page shows, and the plan's
 * file as plain text under a disclosure. Until a resume spends it, each row has a box, ticked unless an approval left
 * the item out, and the foot approves the ticked ones, whole when all are, with the operator's own words after the
 * message the approval writes, as `canopy plan KEY --approve` does. `onChange` hears an approval done or refused, to
 * read again what shows the plan.
 */
export function FeedbackPlanPanel({ plan, onChange }: { plan: FeedbackPlan; onChange: () => void }) {
    const [shown, setShown] = useState(false)
    const open = plan.status !== 'spent'
    return (
        <Panel id="feedback-plan" data-testid="feedback-plan" data-status={plan.status}>
            <PanelHeader label="Feedback plan">
                <span className="flex items-center gap-2">
                    <span className="readout text-xs text-muted-foreground">feedback-plan:{plan.id}</span>
                    <Chip tone={STATUS_TONE[plan.status]} word={plan.status} />
                </span>
            </PanelHeader>
            <div className="flex flex-col gap-2 p-3 text-sm">
                <p className="text-muted-foreground">
                    <RunLink id={plan.run} /> planned this round of feedback for{' '}
                    <TicketLink ticketKey={plan.ticket_key} /> <Age at={plan.created_at} variant="ago" />: its resume
                    acts on the items you approve, and only those. <StatusLine plan={plan} />
                </p>
                {plan.status === 'stale' && <Stale plan={plan} />}
            </div>
            {open ? <Approve key={plan.id} plan={plan} onChange={onChange} /> : <ItemRows items={plan.items} />}
            <Collapsible open={shown} onOpenChange={setShown} className="border-t">
                <div className="flex items-center gap-2 px-3 py-1.5">
                    <Disclosure open={shown} what="the plan" />
                    <span className="text-xs text-muted-foreground">
                        {plan.text === null ? `its file is ${plan.problem ?? 'unreadable'}` : 'as its file stands now'}
                    </span>
                </div>
                <CollapsibleContent>
                    {plan.text !== null && (
                        <div className="border-t px-3 py-2 font-mono text-xs" data-testid="feedback-plan-text">
                            <MemoryText text={plan.text} lines />
                        </div>
                    )}
                </CollapsibleContent>
            </Collapsible>
        </Panel>
    )
}

/**
 * One item's proposal on its thread's card: its number in the plan, what it proposes, whether an approval left it out,
 * and the reply it would draft, plain text, a model's words until a worker drafts and the operator sends them.
 */
export function PlanProposal({ item }: { item: FeedbackPlanItem }) {
    return (
        <div className="mt-2 rounded-md border border-dashed p-2" data-testid="plan-proposal">
            <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="panel-label">Plan item {item.number}</span>
                <Chip word={item.proposal} />
                {item.left_out && <Chip>left out</Chip>}
            </span>
            {item.reply !== null && <MemoryText text={item.reply} lines className="mt-1 block" />}
        </div>
    )
}

/** What the plan's status means now, in a sentence after the line saying who planned it. */
function StatusLine({ plan }: { plan: FeedbackPlan }) {
    switch (plan.status) {
        case 'waiting': {
            return <>It waits on you.</>
        }
        case 'stale': {
            return <>It waits on you, and its PR has moved on.</>
        }
        case 'approved': {
            return (
                <>
                    {plan.approved_channel === 'planner' ? 'Its planner approved it' : 'Approved'}
                    {plan.approved_channel !== null && plan.approved_channel !== 'planner' && (
                        <> via {plan.approved_channel}</>
                    )}
                    {plan.approved_at !== null && (
                        <>
                            {' '}
                            <Age at={plan.approved_at} variant="ago" />
                        </>
                    )}
                    {plan.approved_reason !== null && (
                        <>
                            , saying <MemoryText text={plan.approved_reason} />
                        </>
                    )}
                    {plan.approved_message !== null && <>; message {plan.approved_message} names its items</>}. The next
                    tick may resume {plan.ticket_key} on it, once.
                </>
            )
        }
        case 'spent': {
            return (
                <>
                    {plan.spent_run !== null && <RunLink id={plan.spent_run} />} went ahead on it; feedback since then
                    waits for the next plan.
                </>
            )
        }
    }
}

/** What changed on a stale plan's PRs since it was written, in the harness's words, and what approving it does now. */
function Stale({ plan }: { plan: FeedbackPlan }) {
    return (
        <div className="flex flex-col gap-1 text-status-blocked" data-testid="feedback-plan-stale">
            <span>Since it was written:</span>
            <ul className="list-disc pl-5">
                {plan.changes.map((change) => (
                    <li key={change}>
                        <MemoryText text={change} />
                    </li>
                ))}
            </ul>
            <span>{plan.stale_shown ? AGAIN : REFUSED_ONCE}</span>
        </div>
    )
}

/**
 * The approval form: a row for each item with a box, ticked unless the last approval left it out, the operator's own
 * words, and the button that approves the ticked items, whole when all are, its command on hover. What it did, or why
 * it was refused, goes under it in the CLI's words.
 */
function Approve({ plan, onChange }: { plan: FeedbackPlan; onChange: () => void }) {
    const id = useId()
    const client = useQueryClient()
    const sendKeys = useSendKeys()
    const [ticked, setTicked] = useState<ReadonlySet<number>>(
        () => new Set(plan.items.filter((i) => !i.left_out).map((i) => i.number)),
    )
    const [words, setWords] = useState('')
    const [said, setSaid] = useState<string | null>(null)
    const choice = chosen(plan.items, ticked, words)
    const approve = useMutation({
        mutationFn: () => approveFeedbackPlan(plan.ticket_key, choice),
        onSuccess: (approved) => {
            setSaid(feedbackPlanApprovedText(approved))
            onChange()
            void refreshTicket(client, plan.ticket_key)
        },
        // A stale refusal is recorded, so approving again approves it: read the plan again to say so.
        onError: onChange,
    })
    const some = plan.items.length === 0 || ticked.size > 0
    const whole = ticked.size === plan.items.length

    function tick(n: number, on: boolean) {
        const next = new Set(ticked)
        if (on) {
            next.add(n)
        } else {
            next.delete(n)
        }
        setTicked(next)
    }

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (some && !approve.isPending) {
            setSaid(null)
            approve.mutate()
        }
    }

    return (
        <form onSubmit={submit} aria-label={`Approve feedback plan ${plan.id}`}>
            <ItemRows items={plan.items} ticked={ticked} onTick={tick} />
            <PanelFooter className="flex flex-col items-stretch gap-2">
                <label className="panel-label" htmlFor={`${id}-words`}>
                    Your words, for its resume (optional)
                </label>
                <Textarea
                    id={`${id}-words`}
                    value={words}
                    onChange={(event) => setWords(event.target.value)}
                    onKeyDown={sendKeys.onKeyDown}
                    spellCheck
                    className="min-h-16"
                />
                <span className="flex flex-wrap items-center gap-2">
                    <Button
                        type="submit"
                        disabled={!some || approve.isPending}
                        title={command(plan.ticket_key, choice)}
                        aria-keyshortcuts={sendKeys.shortcut}
                    >
                        <Check />
                        {approveLabel(approve.isPending, whole, ticked.size, plan.items.length)}
                        <SendKeycap keys={sendKeys.shortcut} />
                    </Button>
                    <span className="text-xs text-muted-foreground">{some ? WRITES : NONE_TICKED}</span>
                </span>
                <Notice error={approve.error}>{said}</Notice>
            </PanelFooter>
        </form>
    )
}

// The approve button's label: whole with every item ticked, else how many of them.
function approveLabel(pending: boolean, whole: boolean, ticked: number, items: number): string {
    if (pending) {
        return 'Approving…'
    }
    return whole ? 'Approve whole' : `Approve ${ticked} of ${items}`
}

// What an approval sends for the ticked items: none named when every one is, so it approves the plan whole; else the
// shorter of the items to approve and those to leave, as `--item` or `--leave` would name them.
function chosen(
    items: readonly FeedbackPlanItem[],
    ticked: ReadonlySet<number>,
    words: string,
): { items: number[]; leave: number[]; message: string | null } {
    const message = words.trim() === '' ? null : words
    const kept = items.filter((i) => ticked.has(i.number)).map((i) => i.number)
    const left = items.filter((i) => !ticked.has(i.number)).map((i) => i.number)
    if (left.length === 0) {
        return { items: [], leave: [], message }
    }
    return kept.length < left.length ? { items: kept, leave: [], message } : { items: [], leave: left, message }
}

// The command an approval is, for the button's hover.
function command(key: string, choice: { items: number[]; leave: number[]; message: string | null }): string {
    const named = [...choice.items.map((n) => `--item ${n}`), ...choice.leave.map((n) => `--leave ${n}`)]
    return ['canopy plan', key, '--approve', ...named, ...(choice.message === null ? [] : ['--message TEXT'])].join(' ')
}

/**
 * The plan's items, a row each: its box when `onTick` is given, its number, what it proposes, its author and whether
 * they are trusted, and where it is: its thread's card, which shows its proposed reply, or else the review or other PR
 * it is on, with that reply under the row.
 */
function ItemRows({
    items,
    ticked,
    onTick,
}: {
    items: readonly FeedbackPlanItem[]
    ticked?: ReadonlySet<number>
    onTick?: (n: number, on: boolean) => void
}) {
    if (items.length === 0) {
        return <p className="border-t px-3 py-2 text-sm text-muted-foreground">It covers no review item.</p>
    }
    return (
        <ol className="divide-y border-t" data-testid="feedback-plan-items">
            {items.map((item) => (
                <li
                    key={item.number}
                    className="flex flex-col gap-1 px-3 py-2 text-sm"
                    data-testid="feedback-plan-item"
                >
                    <span className="flex flex-wrap items-center gap-2">
                        {onTick !== undefined && (
                            <Checkbox
                                aria-label={`address item ${item.number}`}
                                checked={ticked?.has(item.number) ?? false}
                                onCheckedChange={(checked) => onTick(item.number, checked === true)}
                            />
                        )}
                        <span className="readout text-xs text-muted-foreground">
                            {item.number}. id {item.item_id}
                        </span>
                        <Chip word={item.proposal} />
                        <span className="font-medium">{item.author ?? 'no author recorded'}</span>
                        {item.trusted && <Chip>trusted</Chip>}
                        {item.left_out && <Chip>left out</Chip>}
                        <span
                            className="ml-auto max-w-72 truncate font-mono text-xs text-muted-foreground"
                            title={where(item)}
                        >
                            {where(item)}
                        </span>
                    </span>
                    {item.thread_id === null && item.reply !== null && (
                        <MemoryText text={item.reply} lines className="block text-muted-foreground" />
                    )}
                </li>
            ))}
        </ol>
    )
}

// Where an item is, for its row.
function where(item: FeedbackPlanItem): string {
    if (item.thread_id !== null) {
        return 'on its thread'
    }
    return item.item === 'review' ? `the review ${item.item_id}` : `on ${item.pr_url}`
}
