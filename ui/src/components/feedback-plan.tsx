import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check } from 'lucide-react'
import { useId, useState } from 'react'
import type { SubmitEvent } from 'react'

import { ApiError } from '@/api/client'
import { approveFeedbackPlan, refreshTicket } from '@/api/mutations'
import type { FeedbackPlan, FeedbackPlanItem, FeedbackPlanStatus } from '@/api/types'
import { Age } from '@/components/age'
import { ApprovedBand } from '@/components/approved-band'
import { Disclosure } from '@/components/disclosure'
import { Textarea } from '@/components/input'
import { LinkOutIcon } from '@/components/link-out-icon'
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
import { messageAnchor } from '@/lib/refs'
import { threadAnchor } from '@/lib/reviews'
import { useSendKeys } from '@/lib/send-key'
import type { Tone } from '@/lib/tone'
import { cn } from '@/lib/utils'

// A plan's status in its chip's color: one waiting on the operator, stale or not, as a waiting draft is; an approved
// one as what the loop is about to act on; a spent one plain.
const STATUS_TONE: Record<FeedbackPlanStatus, Tone> = {
    waiting: 'blocked',
    stale: 'blocked',
    approved: 'running',
    spent: 'plain',
}
// The chip's word for each status: a waiting plan says who it waits on, as a ticket's plan chip does.
const STATUS_WORD: Record<FeedbackPlanStatus, string> = {
    waiting: 'waiting on you',
    stale: 'stale',
    approved: 'approved',
    spent: 'spent',
}
// What approving a stale plan does: refused once, naming what changed, then approved as it is.
const REFUSED_ONCE =
    'The loop plans it again once the PR goes quiet. Approving it now is refused once, naming this; approving it ' +
    'again approves it as it is.'
const AGAIN = 'Approving it again approves it as it is; what changed waits for the next plan.'
// What the stale refusal says under the button, calmly: it is the designed first step, not an error.
const STALE_SAID = 'Refused once, as a stale plan is the first time: approve it as it is to go ahead.'
// The line beside the approve button: with an item ticked, with none, once approved, and with no file to approve.
const WRITES =
    'Approving writes a message on the ticket naming, by number, the items to address and those for the next plan, ' +
    'with your words after it.'
const NONE_TICKED = 'Tick an item to approve, or reply on the ticket to ask for changes.'
const APPROVED = 'Tick other items, or write words for its resume, to approve it again.'
// The chip on an item the last approval did not tick: its resume does not act on it, and the next plan is offered it.
// Never `left out` or `leave`, which is a proposal of its own: a ticked `leave` item approves leaving it be.
const NEXT_PLAN = 'for the next plan'
// The note on a `change` over a waiting draft, which the plan and the draft would each answer in their own way.
const AHEAD = "The plan's resume writes a new reply here; sending this draft first answers ahead of it."

/**
 * The current feedback plan of the PR's ticket (DESIGN §32): where it stands, what changed on its PRs since it was
 * written while it is stale, each item it covers in a row, its number, what it proposes, its author and whether they
 * are trusted, and where it is, with the reply it would draft for one no thread card on the page shows, and the plan's
 * file as plain text under a disclosure. Until a resume spends it, each row has a box, ticked unless an approval put
 * the item off for the next plan, and the foot approves the ticked ones, whole when all are, with the operator's own
 * words after the message the approval writes, as `canopy plan KEY --approve` does. `onChange` hears an approval done
 * or refused, to read again what shows the plan.
 */
export function FeedbackPlanPanel({ plan, onChange }: { plan: FeedbackPlan; onChange: () => void }) {
    const [shown, setShown] = useState(false)
    const open = plan.status !== 'spent'
    // Until it is approved, the line says what approving does; after, only where it stands.
    const deciding = plan.status === 'waiting' || plan.status === 'stale'
    return (
        <Panel id="feedback-plan" data-testid="feedback-plan" data-status={plan.status}>
            <PanelHeader label="Feedback plan">
                <span className="flex items-center gap-2">
                    <span className="readout text-xs text-muted-foreground">feedback-plan:{plan.id}</span>
                    <Chip tone={STATUS_TONE[plan.status]} word={STATUS_WORD[plan.status]} />
                </span>
            </PanelHeader>
            <div className="flex flex-col gap-2 p-3 text-sm">
                <p className="text-muted-foreground">
                    <RunLink id={plan.run} /> planned this round of feedback for{' '}
                    <TicketLink ticketKey={plan.ticket_key} /> <Age at={plan.created_at} variant="ago" />
                    {deciding ? ': its resume acts on the items you approve, and only those.' : '.'}{' '}
                    <StatusLine plan={plan} />
                </p>
                {plan.status === 'stale' && <Stale plan={plan} />}
            </div>
            {open ? <Approve key={plan.id} plan={plan} onChange={onChange} /> : <ItemRows items={plan.items} />}
            {plan.text === null ? (
                <p className="border-t px-3 py-1.5 text-xs text-muted-foreground" data-testid="feedback-plan-no-file">
                    Its file is {plan.problem ?? 'unreadable'}: {plan.path}
                </p>
            ) : (
                <Collapsible open={shown} onOpenChange={setShown} className="border-t">
                    <div className="flex items-center gap-2 px-3 py-1.5">
                        <Disclosure open={shown} what="the plan" />
                        <span className="text-xs text-muted-foreground">as its file stands now</span>
                    </div>
                    <CollapsibleContent>
                        <div className="border-t px-3 py-2 font-mono text-xs" data-testid="feedback-plan-text">
                            <MemoryText text={plan.text} lines />
                        </div>
                    </CollapsibleContent>
                </Collapsible>
            )}
        </Panel>
    )
}

/**
 * One item's proposal on its thread's card: its number in the plan, what it proposes, whether an approval put it off
 * for the next plan, and the reply it would draft, plain text, a model's words until a worker drafts and the operator
 * sends them. Drawn as an inset rule on the thread's card rather than a card of its own. `ahead` says the thread
 * has a waiting draft the plan's resume would answer again, as a `change`, so sending it first answers ahead of it.
 */
export function PlanProposal({ item, ahead = false }: { item: FeedbackPlanItem; ahead?: boolean }) {
    return (
        <div className="mt-2 border-l-2 py-0.5 pl-2.5" data-testid="plan-proposal">
            <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="panel-label">Plan item {item.number}</span>
                <Chip tone={item.proposal} word={item.proposal} />
                {item.left_out && <Chip>{NEXT_PLAN}</Chip>}
            </span>
            {item.reply !== null && <MemoryText text={item.reply} lines className="mt-1 block" />}
            {ahead && (
                <p className="mt-1 text-xs text-status-blocked" data-testid="plan-proposal-ahead">
                    {AHEAD}
                </p>
            )}
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
            return <ApprovedLine plan={plan} />
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

/**
 * How an approved plan was approved: by the operator, from this page or the command line, or by its planner, whose
 * reason is quoted, a model's words; the message the approval wrote links to it in the ticket's conversation.
 */
function ApprovedLine({ plan }: { plan: FeedbackPlan }) {
    const reason = plan.approved_reason
    // The quoted reason ends the sentence when it ends one itself, so no period doubles its own.
    const period = reason !== null && plan.approved_message === null && endsSentence(reason) ? '' : '.'
    return (
        <>
            {approvedBy(plan.approved_channel)}
            {plan.approved_at !== null && (
                <>
                    {' '}
                    <Age at={plan.approved_at} variant="ago" />
                </>
            )}
            {reason !== null && (
                <>
                    , saying “<MemoryText text={reason} />”
                </>
            )}
            {plan.approved_message !== null && (
                <>
                    ;{' '}
                    <Link
                        to="/tickets/$key"
                        params={{ key: plan.ticket_key }}
                        hash={messageAnchor(plan.approved_message)}
                        className="text-accent underline-offset-4 hover:underline"
                    >
                        message {plan.approved_message}
                    </Link>{' '}
                    on the ticket names its items
                </>
            )}
            {period} The next tick may resume {plan.ticket_key} on it, once.
        </>
    )
}

// Who approved the plan, by the channel the approval recorded: the planner, or the operator, wherever they were.
function approvedBy(channel: string | null): string {
    if (channel === 'planner') {
        return 'Its planner approved it'
    }
    return channel === 'cli' ? 'Approved by you, from the command line' : 'Approved by you'
}

// Whether a reason ends a sentence of its own: a period, a question or exclamation mark, a closing quote after one.
function endsSentence(text: string): boolean {
    return /[.!?]["'”’)]*\s*$/u.test(text)
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
 * The approval form: a row for each item with a box, ticked unless the last approval put it off for the next plan,
 * the operator's own words, and the button that approves the ticked items, whole when all are, its command on hover.
 * Approving a stale plan is refused once by design, so that refusal reads as the step it is, not as an error; any
 * other refusal goes under the button in the CLI's words. An approval done is the moment it is (`ApprovedBand`), the
 * words cleared and the button at rest as an outline `Approve again` until a box or the words change, so a second
 * press, or the send key, cannot approve it twice by accident. Nothing can be approved with no item ticked, or with
 * no file to approve.
 */
function Approve({ plan, onChange }: { plan: FeedbackPlan; onChange: () => void }) {
    const id = useId()
    const client = useQueryClient()
    const sendKeys = useSendKeys()
    const [ticked, setTicked] = useState<ReadonlySet<number>>(
        () => new Set(plan.items.filter((i) => !i.left_out).map((i) => i.number)),
    )
    const [words, setWords] = useState('')
    // What the last approval from this form said, numbered so each plays the band again, and whether a box or the
    // words changed since: until one does, approving again would only be refused as the same approval.
    const [done, setDone] = useState<{ text: string; n: number } | null>(null)
    const [changed, setChanged] = useState(false)
    const choice = chosen(plan.items, ticked, words)
    const approve = useMutation({
        mutationFn: () => approveFeedbackPlan(plan.ticket_key, choice),
        onSuccess: (approved) => {
            setDone((last) => ({ text: feedbackPlanApprovedText(approved), n: (last?.n ?? 0) + 1 }))
            setChanged(false)
            setWords('')
            onChange()
            void refreshTicket(client, plan.ticket_key)
        },
        // A stale refusal is recorded, so approving again approves it: read the plan again to say so.
        onError: onChange,
    })
    const missing = plan.text === null
    const some = plan.items.length === 0 || ticked.size > 0
    const again = done !== null || plan.status === 'approved'
    const rested = done !== null && !changed
    const can = some && !missing && !rested && !approve.isPending
    const whole = ticked.size === plan.items.length
    const refusedStale = approve.error instanceof ApiError && approve.error.guard === 'stale'

    function tick(n: number, on: boolean) {
        const next = new Set(ticked)
        if (on) {
            next.add(n)
        } else {
            next.delete(n)
        }
        setTicked(next)
        setChanged(true)
    }

    function write(value: string) {
        setWords(value)
        setChanged(true)
    }

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (can) {
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
                    onChange={(event) => write(event.target.value)}
                    onKeyDown={sendKeys.onKeyDown}
                    spellCheck
                    className="min-h-16"
                />
                <span className="flex flex-wrap items-center gap-2">
                    <Button
                        type="submit"
                        variant={again ? 'outline' : 'default'}
                        disabled={!can}
                        title={command(plan.ticket_key, choice)}
                        aria-keyshortcuts={sendKeys.shortcut}
                    >
                        <Check />
                        {approveLabel(plan, { pending: approve.isPending, again, whole, ticked: ticked.size })}
                        <SendKeycap keys={sendKeys.shortcut} />
                    </Button>
                    <span className="text-xs text-muted-foreground">{hint(plan, { some, rested })}</span>
                </span>
                {done !== null && <ApprovedBand key={done.n} text={done.text} />}
                <Notice error={refusedStale ? undefined : approve.error}>{refusedStale ? STALE_SAID : null}</Notice>
            </PanelFooter>
        </form>
    )
}

// The approve button's label: a stale plan's two steps by name, approving again once it is approved, else whole with
// every item ticked, or how many of them; plain `Approve` with none, since there is nothing to count.
function approveLabel(
    plan: FeedbackPlan,
    { pending, again, whole, ticked }: { pending: boolean; again: boolean; whole: boolean; ticked: number },
): string {
    if (pending) {
        return 'Approving…'
    }
    if (again) {
        return 'Approve again'
    }
    if (plan.status === 'stale') {
        return plan.stale_shown ? 'Approve as it is' : 'Approve stale plan'
    }
    if (ticked === 0 && plan.items.length > 0) {
        return 'Approve'
    }
    return whole ? 'Approve whole' : `Approve ${ticked} of ${plan.items.length}`
}

// The line beside the button: why nothing can be approved now, or what approving writes.
function hint(plan: FeedbackPlan, { some, rested }: { some: boolean; rested: boolean }): string {
    if (plan.text === null) {
        const problem = plan.problem ?? 'unreadable'
        return `Its file is ${problem}, so nothing can be approved: reply on the ticket to ask for a new plan.`
    }
    if (!some) {
        return NONE_TICKED
    }
    return rested ? APPROVED : WRITES
}

// What an approval sends for the ticked items: none named when every one is, so it approves the plan whole; else the
// shorter of the items to approve and those for the next plan, as `--item` or `--leave` would name them.
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
 * The plan's items, a row each: its box when `onTick` is given, its number, the first line of what was said, plain
 * text, and where it is, a link to its thread's card, to the review on its host, or the other PR it is on; under
 * that, muted, what it proposes in its own hue, its author and whether they are trusted, `for the next plan` on one an
 * approval put off, the plan's first line on it, and its id.
 * An item no thread card on the page shows carries its proposed reply, labelled as one, under the row.
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
        return <p className="border-t px-3 py-2 text-sm text-muted-foreground">It covers no item.</p>
    }
    return (
        <ol className="divide-y border-t" data-testid="feedback-plan-items">
            {items.map((item) => (
                <li
                    key={item.number}
                    className="flex flex-col gap-1 px-3 py-2 text-sm"
                    data-testid="feedback-plan-item"
                >
                    <span className="flex items-start gap-2">
                        {onTick !== undefined && (
                            <Checkbox
                                aria-label={`approve item ${item.number}`}
                                checked={ticked?.has(item.number) ?? false}
                                onCheckedChange={(checked) => onTick(item.number, checked === true)}
                                className="mt-0.5"
                            />
                        )}
                        <span className="readout shrink-0 text-xs text-muted-foreground" title={`id ${item.item_id}`}>
                            {item.number}.
                        </span>
                        <span className="min-w-0 grow" data-testid="feedback-plan-said">
                            {item.excerpt === null ? (
                                <span className="text-muted-foreground">{nothingSaid(item)}</span>
                            ) : (
                                <MemoryText text={item.excerpt} />
                            )}
                        </span>
                        <Where item={item} />
                    </span>
                    <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <Chip tone={item.proposal} word={item.proposal} />
                        {raisedByCanopy(item) || (
                            <span className="font-medium text-foreground">{item.author ?? 'no author recorded'}</span>
                        )}
                        {item.trusted && <Chip>trusted</Chip>}
                        {item.left_out && <Chip>{NEXT_PLAN}</Chip>}
                        {item.rationale !== null && (
                            <span className="min-w-0" data-testid="feedback-plan-why">
                                <MemoryText text={item.rationale} />
                            </span>
                        )}
                        <span className="readout ml-auto">id {item.item_id}</span>
                    </span>
                    {item.thread_id === null && item.reply !== null && (
                        <span className="flex flex-col gap-0.5" data-testid="feedback-plan-reply">
                            <span className="panel-label">Proposed reply</span>
                            <MemoryText text={item.reply} lines className="block text-muted-foreground" />
                        </span>
                    )}
                </li>
            ))}
        </ol>
    )
}

// What a row says in place of an excerpt: a review that said nothing, an item no read holds any more, or what canopy
// raised from the PR's state, which no one wrote.
function nothingSaid(item: FeedbackPlanItem): string {
    switch (item.item) {
        case 'review': {
            return 'a review with no words'
        }
        case 'comment': {
            return 'no longer on the PR as read'
        }
        case 'check': {
            return `the check ${item.check ?? 'of no recorded name'} failed at its head`
        }
        case 'conflict': {
            return 'it conflicts with its base'
        }
        case 'blocker': {
            return `the PR it is stacked on merged: ${item.blocker ?? 'no recorded PR'}`
        }
    }
}

/**
 * Where an item is: `on its thread`, a router link to the thread's card on this page (a bare `#` href would go to the
 * root under the page's <base>); `the review`, opening it on its host; or the PR it is on, for one of another PR.
 */
function Where({ item }: { item: FeedbackPlanItem }) {
    const look = 'ml-auto max-w-72 shrink-0 truncate text-xs'
    if (item.thread_id !== null) {
        return (
            <Link
                to="/pull-requests/pr"
                search={{ url: item.pr_url }}
                hash={threadAnchor(item.thread_id)}
                className={cn(look, 'text-accent underline-offset-4 hover:underline')}
            >
                on its thread
            </Link>
        )
    }
    if (item.item === 'review') {
        return item.url === null ? (
            <span className={cn(look, 'font-mono text-muted-foreground')}>the review {item.item_id}</span>
        ) : (
            <a
                href={item.url}
                target="_blank"
                rel="noreferrer noopener"
                className={cn(look, 'inline-flex items-center gap-1 text-accent underline-offset-4 hover:underline')}
            >
                the review
                <LinkOutIcon href={item.url} />
            </a>
        )
    }
    return (
        <span className={cn(look, 'font-mono text-muted-foreground')} title={item.pr_url}>
            on {item.pr_url}
        </span>
    )
}

// Whether canopy raised the item from the PR's state, a failed check, a conflict, or a merged blocker, so it has no
// author.
function raisedByCanopy(item: FeedbackPlanItem): boolean {
    return item.item === 'check' || item.item === 'conflict' || item.item === 'blocker'
}
