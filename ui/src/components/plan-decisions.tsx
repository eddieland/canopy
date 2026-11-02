import { ArrowDown } from 'lucide-react'
import { useId } from 'react'
import type { Ref } from 'react'

import { LetteredOption } from '@/components/lettered-option'
import { InlineCode } from '@/components/rich-text'
import { RadioGroup, RadioGroupRow } from '@/components/ui/radio-group'
import { usePending } from '@/hooks/use-pending'
import { OPTION_HOVER, OPTION_ROW } from '@/lib/lettered-options'
import { decisionAnswers } from '@/lib/plan-decisions'
import type { PlanDecision } from '@/lib/plan-decisions'
import { cn } from '@/lib/utils'

// What the panel says while every decision has the planner's choice picked.
const UNANSWERED =
    "Each has the planner's choice picked. Pick another to answer it: the answer goes with Approve or Ask for changes."

/**
 * A plan's open decisions (`planDecisions`), answered where the plan is read rather than in a round of comments: each
 * drawn as a run's question is (`ProgressQuestion`), in its box, its question, then its lettered options
 * (`LetteredOption`), the planner's `recommended` and the one picked checked. Each decision is a radio group, the
 * planner's choice picked at first. Picking another answers it, a line that goes with Approve to the implement and with
 * Ask for changes to the planner (`decisionAnswers`); leaving the planner's choice sends nothing. The picks are the
 * caller's state, by decision number, kept on the page alone: while any answers, it holds words not yet sent, which
 * leaving the page asks about. The plan's words are the planner's, so they stay text, their code spans set as code
 * (`InlineCode`).
 */
export function PlanDecisions({
    decisions,
    picks,
    onPick,
    ref,
}: {
    /** The plan's open decisions, in its order. */
    decisions: readonly PlanDecision[]
    /** The letter the operator picked for each decision, by its number; one not here is the planner's choice. */
    picks: ReadonlyMap<number, string>
    /** Called with a decision's number and the letter picked for it. */
    onPick: (decision: number, letter: string) => void
    /** The panel, which `DecisionsJump` scrolls into view and focuses. */
    ref?: Ref<HTMLElement>
}) {
    const id = useId()
    const answered = decisionAnswers(decisions, picks).length
    usePending(answered > 0)
    const goes = answered === 1 ? '1 answer goes' : `${answered} answers go`
    const told =
        answered === 0 ? UNANSWERED : `${goes} with Approve, to the implement, or with Ask for changes, to the planner.`
    return (
        <section
            ref={ref}
            aria-labelledby={id}
            // Focused by the foot's jump (`DecisionsJump`), so the keyboard goes on from here to the first decision; a
            // place to stand, not a control, so it draws no ring.
            tabIndex={-1}
            className="flex flex-col gap-3 border-t px-6 py-4 outline-none"
            data-testid="plan-decisions"
        >
            <div className="flex max-w-3xl flex-col gap-1">
                <h3 id={id} className="panel-label font-medium text-foreground">
                    Open decisions
                </h3>
                <p className="text-xs text-muted-foreground">{told}</p>
            </div>
            {decisions.map((decision) => (
                <DecisionChoice
                    key={decision.number}
                    decision={decision}
                    picked={picks.get(decision.number) ?? decision.chosen}
                    onPick={(letter) => onPick(decision.number, letter)}
                />
            ))}
        </section>
    )
}

/**
 * The jump to a plan's open decisions, from its sticky foot, where it is on screen however far the plan scrolls while
 * the decisions sit under its last line: `↓ 2 open decisions`, then, once some are answered, `↓ 1 of 2 answered`. It
 * says they are there, and takes the operator to them; it gates nothing, since each already has the planner's choice
 * picked. It counts the decisions as the plan reads now, and the answers as `decisionAnswers` does, so an edit to the
 * plan's Decisions changes both.
 */
export function DecisionsJump({
    decisions,
    picks,
    onJump,
}: {
    /** The plan's open decisions, as the panel shows them. */
    decisions: readonly PlanDecision[]
    /** The letter the operator picked for each decision, by its number, as the panel has them. */
    picks: ReadonlyMap<number, string>
    /** Brings the panel into view. */
    onJump: () => void
}) {
    const count = decisions.length
    const answered = decisionAnswers(decisions, picks).length
    return (
        <button
            type="button"
            onClick={onJump}
            title="Go to the open decisions"
            className={cn(
                'mr-3 inline-flex items-baseline gap-1 rounded-sm font-mono text-xs whitespace-nowrap text-accent',
                'underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50',
            )}
        >
            <ArrowDown aria-hidden className="size-3 self-center" />
            {answered === 0 ? (
                `${count} open ${count === 1 ? 'decision' : 'decisions'}`
            ) : (
                <span>
                    {/* For its name, which `1 of 2 answered` alone would leave without its subject. */}
                    <span className="sr-only">Open decisions: </span>
                    {answered} of {count} answered
                </span>
            )}
        </button>
    )
}

// One decision in a run's question's box: which it is and whether you answered it, its question, then its options,
// each a row that is its radio.
function DecisionChoice({
    decision,
    picked,
    onPick,
}: {
    decision: PlanDecision
    picked: string
    onPick: (letter: string) => void
}) {
    const answered = picked !== decision.chosen
    return (
        <div className="flex max-w-3xl flex-col gap-2 rounded-md border bg-surface-raised/50 p-3">
            <p className="text-xs text-muted-foreground">
                Decision {decision.number} · {answered ? `answered ${picked}` : "the planner's choice"}
            </p>
            <p className="text-sm font-medium text-pretty">
                <InlineCode text={decision.question} links={false} />
            </p>
            <RadioGroup
                value={picked}
                onValueChange={onPick}
                aria-label={`Decision ${decision.number}: ${decision.question}`}
            >
                {decision.options.map((option) => {
                    const recommended = option.letter === decision.chosen
                    return (
                        <RadioGroupRow
                            key={option.letter}
                            value={option.letter}
                            className={cn(OPTION_ROW, OPTION_HOVER)}
                            aria-label={`${option.letter}: ${option.text}${recommended ? ', recommended' : ''}`}
                        >
                            <LetteredOption
                                letter={option.letter}
                                chosen={option.letter === picked}
                                recommended={recommended}
                                answered={answered && option.letter === picked}
                            >
                                <InlineCode text={option.text} links={false} />
                            </LetteredOption>
                        </RadioGroupRow>
                    )
                })}
            </RadioGroup>
        </div>
    )
}
