import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Circle, CircleCheck, CircleMinus, Clock, Hourglass } from 'lucide-react'
import { useState } from 'react'

import { answerQuestion, refreshAnswered } from '@/api/mutations'
import type { AnswerTarget } from '@/api/mutations'
import type { RunCard, RunCardQuestion } from '@/api/types'
import { Age } from '@/components/age'
import { Disclosure } from '@/components/disclosure'
import { LinkedText } from '@/components/linked-text'
import { Notice } from '@/components/notice'
import { Panel, PanelHeader } from '@/components/panel'
import { RunDot } from '@/components/status'
import { Clipped } from '@/components/tip'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { answeredText } from '@/lib/outcomes'
import { useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/**
 * A running worker's, planner's, reviewer's, or task's progress, in its own words (DESIGN §41), whole: its summary, how
 * much of its steps is done as a meter, a question it asks you, then its work as one checklist, the steps when it named
 * any and what is done, what it does now, and what is next when it did not, then what it works around. `freshness`
 * leads with when it last wrote an update; a page that says so in a panel's header (`ProgressFreshness`) leaves it out.
 * `answers`, the run or review it is, lets the page answer its question. Agent text, rendered as text.
 */
export function RunProgress({
    card,
    running,
    answers,
    freshness = true,
    className,
}: {
    card: RunCard
    running: boolean
    answers?: AnswerTarget
    freshness?: boolean
    className?: string
}) {
    const items = checklist(card, useNow())
    const counted = card.steps.length > 0
    return (
        <div className={cn('flex flex-col gap-3', className)} data-testid="run-progress">
            <div className="flex flex-col gap-1.5">
                {freshness && <ProgressFreshness card={card} running={running} />}
                <p className="text-sm font-medium text-pretty">
                    <LinkedText text={card.summary} />
                </p>
                {counted && <MeterLine card={card} running={running} />}
            </div>
            {card.question !== null && (
                // Keyed by when it was asked, so what an answer said goes with the question it answered.
                <ProgressQuestion
                    key={card.question.asked_at}
                    question={card.question}
                    running={running}
                    answers={answers}
                />
            )}
            <Checklist items={items} now={card.now} counted={counted} />
            {card.stuck !== null && (
                <p className="flex items-baseline gap-2 text-sm" data-testid="run-progress-stuck">
                    <Hourglass aria-hidden className="size-3 shrink-0 translate-y-0.5 text-muted-foreground" />
                    <span className="shrink-0 text-xs text-muted-foreground">working around</span>
                    <span className="min-w-0 break-words">
                        <LinkedText text={card.stuck} />
                    </span>
                </p>
            )}
            {counted && (card.done.length > 0 || card.next.length > 0) && <WroteDoneNext card={card} />}
        </div>
    )
}

/**
 * A run's, review's, or task run's progress as a panel of its own, which leads its page: `Progress` while the run runs,
 * `Last progress` once it ended, when it last wrote an update on the header's right, then the progress whole. `answers`
 * lets the page answer its question; a task's run asks none, so its page names no target.
 */
export function ProgressPanel({ card, running, answers }: { card: RunCard; running: boolean; answers?: AnswerTarget }) {
    return (
        <Panel data-testid="progress-panel">
            <PanelHeader label={running ? 'Progress' : 'Last progress'}>
                <ProgressFreshness card={card} running={running} />
            </PanelHeader>
            <RunProgress card={card} running={running} answers={answers} freshness={false} className="p-3" />
        </Panel>
    )
}

/**
 * When the agent last wrote an update, in time and tool calls. While the run runs, one too long ago reads `stale`
 * beside a clock, judged against the page's clock so it turns without a new read: a fact about the record, not a
 * request of the operator, so it never wears the color of what waits on them. An ended run's last update never does.
 */
export function ProgressFreshness({
    card,
    running,
    className,
}: {
    card: RunCard
    running: boolean
    className?: string
}) {
    const now = useNow()
    const stale = running && isStale(card, now)
    const calls = card.calls_since === 1 ? '1 tool call' : `${card.calls_since} tool calls`
    return (
        <p
            className={cn('flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground', className)}
            data-testid="run-progress-freshness"
        >
            {stale && (
                <span className="flex items-center gap-1 text-foreground">
                    <Clock aria-hidden className="size-3" />
                    stale
                </span>
            )}
            <span className="flex items-baseline gap-1">
                {running && !stale ? 'updated' : 'last update'}
                <Age at={card.at} variant="ago" />
            </span>
            <span>·</span>
            <span>{running ? `${calls} since` : `${calls} before the run ended`}</span>
        </p>
    )
}

/**
 * A running run's progress on one line, for a row: a small meter of its steps when it has any, what it says it does
 * now, that it asks you a question still unanswered, and when it last wrote an update, `stale` beside a clock as
 * `ProgressFreshness` marks it.
 */
export function RunProgressLine({ card, className }: { card: RunCard; className?: string }) {
    const stale = isStale(card, useNow())
    return (
        <span className={cn('flex min-w-0 items-center gap-2 text-xs', className)} data-testid="run-progress-line">
            {card.steps.length > 0 && (
                <span className="flex shrink-0 items-center gap-1.5">
                    <ProgressMeter card={card} running className="w-16" />
                    <span className="readout text-muted-foreground">{doneOf(card)}</span>
                </span>
            )}
            <Clipped text={card.now} className="min-w-0" />
            {card.question !== null && card.question.answer === null && (
                <span className="shrink-0 text-status-blocked">asks you</span>
            )}
            <span className="flex shrink-0 items-center gap-1 text-muted-foreground">
                {stale && <Clock aria-hidden className="size-3 text-foreground" />}
                {stale && <span className="text-foreground">stale</span>}
                <Age at={card.at} variant="ago" />
            </span>
        </span>
    )
}

/**
 * A run's steps as a bar of segments, one each, in its status's color. Only a done step fills its segment, in
 * `status-done`, so the filled segments are the count beside the meter; working fills half of the track in
 * `status-running`, a barber pole's stripes drifting along it while the run runs, blocked or stuck half in
 * `muted-foreground`, to do is the bare track, skipped the track fainter still. Drawn, so its words are its label.
 */
export function ProgressMeter({ card, running, className }: { card: RunCard; running: boolean; className?: string }) {
    const items = checklist(card, useNow())
    const done = items.filter((i) => i.status === 'done').length
    const counted = items.filter((i) => i.status !== 'skipped').length
    return (
        <span className={cn('flex h-1.5 min-w-0 gap-0.5', className)} data-testid="progress-meter">
            <span className="sr-only">{`${done} of ${counted} steps done`}</span>
            {items.map((item, i) => (
                <span
                    key={`${i}-${item.title}`}
                    aria-hidden
                    className={cn('h-full min-w-1 flex-1 overflow-hidden rounded-xs', SEGMENT[item.status])}
                >
                    {HALF[item.status] !== undefined && (
                        <span
                            className={cn(
                                'block h-full w-1/2',
                                HALF[item.status],
                                running && item.status === 'working' && 'animate-barber',
                            )}
                        />
                    )}
                </span>
            ))}
        </span>
    )
}

/** Whether a running run's progress is stale at `now`: too many tool calls since its last update, as the server says,
 * or its time to go stale has come. An ended run's never is. */
function isStale(card: RunCard, now: number): boolean {
    return card.stale || (card.stale_at !== null && now >= Date.parse(card.stale_at))
}

/** Where one entry of the checklist stands: a step's status, with `stuck` for a working step past its time. */
type ItemStatus = RunCard['steps'][number]['status'] | 'stuck'

/** One entry of the checklist: a step, or one of what is done, what it does now, and what is next. */
interface Item {
    /** What it is, in the agent's words. */
    title: string
    /** Where it stands. */
    status: ItemStatus
    /** The stage it belongs to, for a step that names one. */
    stage: string | null
    /** The proof of a done entry, for one taken from what is done. */
    proof: string | null
}

/** Each status's segment: done filled, the rest the track, fainter for skipped. */
const SEGMENT: Record<ItemStatus, string> = {
    done: 'bg-status-done',
    working: 'bg-border',
    stuck: 'bg-border',
    blocked: 'bg-border',
    not_started: 'bg-border',
    skipped: 'bg-border/40',
}

/** The half of the track a step under way fills, so it never reads as done. */
const HALF: Partial<Record<ItemStatus, string>> = {
    working: 'bg-status-running',
    stuck: 'bg-muted-foreground',
    blocked: 'bg-muted-foreground',
}

/**
 * The work as one list: its steps when it named any, a working step past its `stuck_at` marked stuck at `now`; else
 * what is done, what it does now, and what is next, in that order, as if each were a step.
 */
function checklist(card: RunCard, now: number): Item[] {
    if (card.steps.length > 0) {
        return card.steps.map((step) => ({
            title: step.title,
            status: step.stuck_at !== null && now >= Date.parse(step.stuck_at) ? 'stuck' : step.status,
            stage: step.stage ?? null,
            proof: null,
        }))
    }
    return [
        ...card.done.map((d) => ({ title: d.step, status: 'done' as const, stage: null, proof: d.proof })),
        { title: card.now, status: 'working' as const, stage: null, proof: null },
        ...card.next.map((n) => ({ title: n, status: 'not_started' as const, stage: null, proof: null })),
    ]
}

/** How many steps are done of those counted, as `2/4`. */
function doneOf(card: RunCard): string {
    const counted = card.steps.filter((s) => s.status !== 'skipped')
    return `${counted.filter((s) => s.status === 'done').length}/${counted.length}`
}

/** The meter, then how many steps are done of those counted, and the stage under way. */
function MeterLine({ card, running }: { card: RunCard; running: boolean }) {
    const counted = card.steps.filter((step) => step.status !== 'skipped')
    const done = counted.filter((step) => step.status === 'done').length
    return (
        <div className="flex max-w-xl items-center gap-3">
            <ProgressMeter card={card} running={running} className="flex-1" />
            <span className="shrink-0 text-xs text-muted-foreground">
                <span className="readout text-foreground">{done}</span> of{' '}
                <span className="readout text-foreground">{counted.length}</span> done
                {card.stage !== null && <span> · stage {card.stage}</span>}
            </span>
        </div>
    )
}

/** What each status reads as beside its mark, for a reader of the words alone. */
const STATUS_WORD: Record<ItemStatus, string> = {
    done: 'done',
    working: 'working',
    stuck: 'stuck',
    blocked: 'blocked',
    not_started: 'to do',
    skipped: 'skipped',
}

/**
 * Each entry with a mark of where it stands and its title: a working one pulses and, when its steps are counted, has
 * what the agent says it does now under it, unless that only says the step's title again. When no step is working,
 * what it does now leads the list.
 */
function Checklist({ items, now, counted }: { items: readonly Item[]; now: string; counted: boolean }) {
    const working = items.some((i) => i.status === 'working' || i.status === 'stuck')
    return (
        <div className="flex flex-col gap-1" data-testid="run-progress-steps">
            {counted && !working && (
                <p className="text-xs text-muted-foreground">
                    now <span className="text-foreground">{now}</span>
                </p>
            )}
            <ol className="flex flex-col gap-1">
                {items.map((item, i) => (
                    <li key={`${i}-${item.title}`} className="flex gap-2.5 text-sm">
                        <span className="flex h-5 w-3 shrink-0 items-center justify-center">
                            <Mark status={item.status} />
                        </span>
                        <span className="sr-only">{STATUS_WORD[item.status]}</span>
                        <span className="flex min-w-0 flex-col">
                            <span
                                className={cn(
                                    'break-words',
                                    (item.status === 'not_started' || item.status === 'skipped') &&
                                        'text-muted-foreground',
                                )}
                            >
                                <LinkedText text={item.title} />
                                {item.proof !== null && (
                                    <span className="font-mono text-xs text-muted-foreground">
                                        {' '}
                                        <LinkedText text={item.proof} />
                                    </span>
                                )}
                                {item.stage !== null && (
                                    <span className="text-xs text-muted-foreground"> · {item.stage}</span>
                                )}
                                {(item.status === 'stuck' ||
                                    item.status === 'blocked' ||
                                    item.status === 'skipped') && (
                                    <span className="text-xs text-muted-foreground"> · {STATUS_WORD[item.status]}</span>
                                )}
                            </span>
                            {counted &&
                                (item.status === 'working' || item.status === 'stuck') &&
                                !sameWords(now, item.title) && (
                                    <span className="text-xs text-muted-foreground">
                                        now <span className="text-foreground">{now}</span>
                                    </span>
                                )}
                        </span>
                    </li>
                ))}
            </ol>
        </div>
    )
}

/** Whether two lines say the same words, apart from case, spacing, and a closing period. */
function sameWords(a: string, b: string): boolean {
    return words(a) === words(b)
}

/** A line's words, lowercased and single-spaced, without a closing period. */
function words(line: string): string {
    return line
        .toLowerCase()
        .trim()
        .replace(/[.…]+$/u, '')
        .split(/\s+/u)
        .filter(Boolean)
        .join(' ')
}

/** The mark that leads an entry: a check, a pulsing dot, an hourglass, a dash, or an empty ring. */
function Mark({ status }: { status: ItemStatus }) {
    return MARK[status]
}

const MUTED_MARK = 'size-3 text-muted-foreground'
const MARK: Record<ItemStatus, React.ReactNode> = {
    done: <CircleCheck aria-hidden className="size-3 text-status-done" />,
    working: <RunDot state="running" />,
    stuck: <Hourglass aria-hidden className={MUTED_MARK} />,
    blocked: <Hourglass aria-hidden className={MUTED_MARK} />,
    skipped: <CircleMinus aria-hidden className={MUTED_MARK} />,
    not_started: <Circle aria-hidden className={MUTED_MARK} />,
}

/**
 * Beside counted steps, what the agent wrote is done, with the proof of each, and what is next, folded: the steps say
 * where the work stands, and these are its notes on them.
 */
function WroteDoneNext({ card }: { card: RunCard }) {
    const [open, setOpen] = useState(false)
    return (
        <Collapsible open={open} onOpenChange={setOpen}>
            <Disclosure open={open} what="done and next" className="-ml-2" />
            <CollapsibleContent className="flex flex-col gap-1 pt-1">
                {card.done.map((d, i) => (
                    <NoteLine key={`done-${i}`} label="done">
                        <LinkedText text={d.step} />
                        <span className="font-mono text-xs text-muted-foreground">
                            {' '}
                            <LinkedText text={d.proof} />
                        </span>
                    </NoteLine>
                ))}
                {card.next.map((n, i) => (
                    <NoteLine key={`next-${i}`} label="next">
                        <LinkedText text={n} />
                    </NoteLine>
                ))}
            </CollapsibleContent>
        </Collapsible>
    )
}

function NoteLine({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <p className="flex gap-2.5 text-sm">
            <span className="w-8 shrink-0 font-mono text-xs leading-5 text-muted-foreground">{label}</span>
            <span className="min-w-0 break-words">{children}</span>
        </p>
    )
}

/** The letters a question's options go by, in order. */
const LETTERS = ['A', 'B', 'C', 'D', 'E'] as const

/**
 * The agent's question: whether it waits on you, the question, and each option by its letter, the one the agent
 * recommends marked as the one it works toward meanwhile, and once you answered, your letter. While it waits it sits on
 * the tint of what waits on you. While the run runs and the page knows which it is (`answers`), each other option is a
 * button that answers with its letter, as `canopy reply run:ID LETTER` does; the agent hears it on its next tool call,
 * and a later answer replaces it. A question asked since the page read it is refused `moved_on`. `onAnswered` hears
 * what an answer did, in the CLI's words, for a page the answer takes the question off, as the attention list's item.
 */
export function ProgressQuestion({
    question,
    running,
    answers,
    onAnswered,
}: {
    question: RunCardQuestion
    running: boolean
    answers: AnswerTarget | undefined
    onAnswered?: (said: string) => void
}) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const mutation = useMutation({
        mutationFn: ({ target, letter }: { target: AnswerTarget; letter: string }) =>
            answerQuestion(target, letter, question.asked_at),
        onSuccess: (answered, { target }) => {
            setSaid(answeredText(answered))
            onAnswered?.(answeredText(answered))
            void refreshAnswered(client, target)
        },
    })
    const waiting = question.answer === null && running
    let state = 'run ended before an answer'
    if (question.answer !== null) {
        state = `answered ${question.answer}`
    } else if (running) {
        state = 'asks you'
    }
    return (
        <div
            className={cn(
                'flex max-w-3xl flex-col gap-2 rounded-md border p-3',
                waiting ? 'border-status-blocked/40 bg-status-blocked/8' : 'bg-surface-raised/50',
            )}
            data-testid="run-progress-question"
        >
            <p className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
                <span className={cn(waiting && 'font-medium text-status-blocked')}>{state}</span>
                <Age at={question.asked_at} variant="ago" />
                {waiting && <span>· it hears your answer on its next tool call</span>}
            </p>
            <p className="text-sm font-medium text-pretty">
                <LinkedText text={question.ask} />
            </p>
            <ol className="flex flex-col gap-0.5">
                {question.options.map((option, i) => {
                    const letter = LETTERS[i] ?? '?'
                    const chosen = letter === question.answer
                    const body = (
                        <>
                            <span
                                className={cn(
                                    'grid size-5 shrink-0 place-items-center rounded-xs border font-mono text-xs',
                                    chosen
                                        ? 'border-status-done/40 bg-status-done/12 text-status-done'
                                        : 'bg-surface text-muted-foreground',
                                )}
                            >
                                {chosen ? <Check aria-hidden className="size-3" /> : letter}
                            </span>
                            <span className="min-w-0 flex-1 break-words">
                                <LinkedText text={option} />
                            </span>
                            {letter === question.recommend && (
                                <span className="shrink-0 text-xs text-muted-foreground">
                                    {waiting ? 'recommended · working toward it' : 'recommended'}
                                </span>
                            )}
                            {chosen && <span className="shrink-0 text-xs text-status-done">your answer</span>}
                        </>
                    )
                    const row = 'flex w-full items-center gap-2.5 rounded-sm px-2 py-1 text-left text-sm'
                    return (
                        <li key={letter}>
                            {running && answers !== undefined && !chosen ? (
                                <button
                                    type="button"
                                    className={cn(
                                        row,
                                        'hover:bg-surface-raised focus-visible:ring-2 focus-visible:ring-ring',
                                        'outline-none disabled:opacity-50',
                                    )}
                                    disabled={mutation.isPending}
                                    aria-label={`Answer ${letter}: ${option}`}
                                    onClick={() => mutation.mutate({ target: answers, letter })}
                                >
                                    {body}
                                </button>
                            ) : (
                                <div className={row}>{body}</div>
                            )}
                        </li>
                    )
                })}
            </ol>
            <Notice error={mutation.error}>{said}</Notice>
        </div>
    )
}
