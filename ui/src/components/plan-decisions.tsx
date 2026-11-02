import { useId } from 'react'

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
}: {
    /** The plan's open decisions, in its order. */
    decisions: readonly PlanDecision[]
    /** The letter the operator picked for each decision, by its number; one not here is the planner's choice. */
    picks: ReadonlyMap<number, string>
    /** Called with a decision's number and the letter picked for it. */
    onPick: (decision: number, letter: string) => void
}) {
    const id = useId()
    const answered = decisionAnswers(decisions, picks).length
    usePending(answered > 0)
    const goes = answered === 1 ? '1 answer goes' : `${answered} answers go`
    const told =
        answered === 0 ? UNANSWERED : `${goes} with Approve, to the implement, or with Ask for changes, to the planner.`
    return (
        <section aria-labelledby={id} className="flex flex-col gap-3 border-t px-6 py-4" data-testid="plan-decisions">
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
