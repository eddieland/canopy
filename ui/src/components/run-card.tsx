import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { answerQuestion, refreshAnswered } from '@/api/mutations'
import type { AnswerTarget } from '@/api/mutations'
import type { RunCard, RunCardQuestion } from '@/api/types'
import { Age } from '@/components/age'
import { LinkedText } from '@/components/linked-text'
import { Notice } from '@/components/notice'
import { Clipped } from '@/components/tip'
import { Button } from '@/components/ui/button'
import { answeredText } from '@/lib/outcomes'
import { useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/**
 * Where a worker's, planner's, or reviewer's work stands, in its own words: its card (DESIGN §41), whole. How old it
 * is leads, in tool calls and time; while the run runs, a card that has gone too long without an update is marked
 * stale in the blocked color rather than going quiet. Then its summary, what it does now, what is done with the proof
 * of each, what is next, what is in its way, for a long job its steps, how much of them is done, and the stage under
 * way, and a question it asks you, which `answers`, the run or review it is, lets the page answer. Agent text, rendered
 * as text.
 */
export function RunCardView({ card, running, answers }: { card: RunCard; running: boolean; answers?: AnswerTarget }) {
    const stale = isStale(card, useNow())
    return (
        <div
            className={cn('flex flex-col gap-1.5 border-l-2 pl-3', stale ? 'border-status-blocked' : 'border-border')}
            data-testid="run-card"
        >
            <CardAge card={card} running={running} stale={stale} />
            <p className="text-sm">
                <LinkedText text={card.summary} />
            </p>
            <CardLine label="now">
                <LinkedText text={card.now} />
            </CardLine>
            {card.done.map((done, i) => (
                <CardLine key={`done-${i}`} label="done">
                    <LinkedText text={done.step} />
                    <span className="font-mono text-xs text-muted-foreground">
                        {' '}
                        <LinkedText text={done.proof} />
                    </span>
                </CardLine>
            ))}
            {card.next.map((step, i) => (
                <CardLine key={`next-${i}`} label="next">
                    <LinkedText text={step} />
                </CardLine>
            ))}
            {card.stuck !== null && (
                <CardLine label="stuck" labelClassName="text-status-blocked">
                    <LinkedText text={card.stuck} />
                </CardLine>
            )}
            {card.question !== null && <CardQuestion question={card.question} running={running} answers={answers} />}
            {card.steps.length > 0 && <CardSteps card={card} />}
        </div>
    )
}

/**
 * A running run's card on one line, for a row: what it says it does now, how much of its steps is done when it has
 * any, that it asks you a question still unanswered, and how old the card is, marked stale as `RunCardView` marks it.
 */
export function RunCardNow({ card, className }: { card: RunCard; className?: string }) {
    const stale = isStale(card, useNow())
    return (
        <span className={cn('flex min-w-0 items-center gap-2 text-xs', className)} data-testid="run-card-now">
            <span className={cn('shrink-0', stale ? 'text-status-blocked' : 'text-muted-foreground')}>
                {stale ? 'stale card' : 'now'}
            </span>
            <Clipped text={card.now} className="min-w-0" />
            {card.percent !== null && <span className="readout shrink-0 text-muted-foreground">{card.percent}%</span>}
            {card.question !== null && card.question.answer === null && (
                <span className="shrink-0 text-status-blocked">asks you</span>
            )}
            <Age at={card.at} variant="ago" className="shrink-0" />
        </span>
    )
}

/**
 * Whether a running run's card is stale at `now`: it has gone too many tool calls without an update, as the server
 * says, or its time to go stale has come. An ended run's never is.
 */
function isStale(card: RunCard, now: number): boolean {
    return card.stale || (card.stale_at !== null && now >= Date.parse(card.stale_at))
}

function CardAge({ card, running, stale }: { card: RunCard; running: boolean; stale: boolean }) {
    const calls = card.calls_since === 1 ? '1 tool call' : `${card.calls_since} tool calls`
    return (
        <p className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
            <span>{running ? 'card' : 'last card'}</span>
            <Age at={card.at} variant="ago" />
            <span>{running ? `${calls} since` : `${calls} before the run ended`}</span>
            {stale && <span className="text-status-blocked">stale</span>}
        </p>
    )
}

/** The letters a question's options go by, in order. */
const LETTERS = ['A', 'B', 'C', 'D', 'E'] as const

/**
 * A card's question: whether it waits on you, the question, and each option by its letter, the one the agent
 * recommends marked, and once you answered, your letter. While the run runs and the page knows which it is
 * (`answers`), each other option is a button that answers with its letter, as `canopy reply run:ID LETTER` does; the
 * agent hears it on its next tool call, and a later answer replaces it. A card that asks another question since the
 * page read it is refused `moved_on`.
 */
function CardQuestion({
    question,
    running,
    answers,
}: {
    question: RunCardQuestion
    running: boolean
    answers: AnswerTarget | undefined
}) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const mutation = useMutation({
        mutationFn: ({ target, letter }: { target: AnswerTarget; letter: string }) =>
            answerQuestion(target, letter, question.asked_at),
        onSuccess: (answered, { target }) => {
            setSaid(answeredText(answered))
            void refreshAnswered(client, target)
        },
    })
    let state = 'never answered'
    if (question.answer !== null) {
        state = `answered ${question.answer}`
    } else if (running) {
        state = 'asks you'
    }
    return (
        <div className="flex flex-col gap-1 pt-1" data-testid="run-card-question">
            <p className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
                <span className={cn(question.answer === null && running && 'text-status-blocked')}>{state}</span>
                <Age at={question.asked_at} variant="ago" />
            </p>
            <p className="text-sm">
                <LinkedText text={question.ask} />
            </p>
            <ol className="flex flex-col gap-1">
                {question.options.map((option, i) => {
                    const letter = LETTERS[i] ?? '?'
                    const chosen = letter === question.answer
                    return (
                        <li key={letter} className="flex items-baseline gap-2 text-sm">
                            <span className="w-4 shrink-0 font-mono text-xs text-muted-foreground">{letter}</span>
                            <span className="min-w-0 break-words">
                                <LinkedText text={option} />
                                {letter === question.recommend && (
                                    <span className="text-xs text-muted-foreground"> · recommended</span>
                                )}
                                {chosen && <span className="text-xs text-status-done"> · your answer</span>}
                            </span>
                            {running && answers !== undefined && !chosen && (
                                <Button
                                    size="xs"
                                    variant="outline"
                                    className="ml-auto shrink-0"
                                    disabled={mutation.isPending}
                                    aria-label={`Answer ${letter}: ${option}`}
                                    onClick={() => mutation.mutate({ target: answers, letter })}
                                >
                                    answer {letter}
                                </Button>
                            )}
                        </li>
                    )
                })}
            </ol>
            <Notice error={mutation.error}>{said}</Notice>
        </div>
    )
}

/** What each step's status reads as, and its color. */
const STEP_STATUS: Record<RunCard['steps'][number]['status'], { word: string; tone: string }> = {
    not_started: { word: 'to do', tone: 'text-muted-foreground' },
    working: { word: 'working', tone: 'text-status-running' },
    blocked: { word: 'blocked', tone: 'text-status-blocked' },
    done: { word: 'done', tone: 'text-status-done' },
    skipped: { word: 'skipped', tone: 'text-muted-foreground' },
}

/**
 * A card's steps: how much is done and the working step's stage, then each step with its status and stage. A working
 * step past its `stuck_at` reads `stuck` in the blocked color, judged against the page's clock.
 */
function CardSteps({ card }: { card: RunCard }) {
    const now = useNow()
    return (
        <div className="flex flex-col gap-0.5 pt-1" data-testid="run-card-steps">
            <p className="text-xs text-muted-foreground">
                {card.percent === null ? 'steps' : <span className="readout">{card.percent}% done</span>}
                {card.stage !== null && <span> · stage {card.stage}</span>}
            </p>
            <ol className="flex flex-col gap-0.5">
                {card.steps.map((step, i) => {
                    const stuck = step.stuck_at !== null && now >= Date.parse(step.stuck_at)
                    const { word, tone } = stuck
                        ? { word: 'stuck', tone: 'text-status-blocked' }
                        : STEP_STATUS[step.status]
                    return (
                        <li key={`${i}-${step.title}`} className="flex gap-2 text-sm">
                            <span className={cn('w-14 shrink-0 font-mono text-xs leading-5', tone)}>{word}</span>
                            <span className="min-w-0 break-words">
                                <LinkedText text={step.title} />
                                {step.stage !== null && (
                                    <span className="text-xs text-muted-foreground"> · {step.stage}</span>
                                )}
                            </span>
                        </li>
                    )
                })}
            </ol>
        </div>
    )
}

function CardLine({
    label,
    labelClassName,
    children,
}: {
    label: string
    labelClassName?: string
    children: React.ReactNode
}) {
    return (
        <p className="flex gap-2 text-sm">
            <span className={cn('w-10 shrink-0 font-mono text-xs leading-5 text-muted-foreground', labelClassName)}>
                {label}
            </span>
            <span className="min-w-0 break-words">{children}</span>
        </p>
    )
}
