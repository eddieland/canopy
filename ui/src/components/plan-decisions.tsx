import { useId } from 'react'

import { InlineCode } from '@/components/rich-text'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { usePending } from '@/hooks/use-pending'
import { decisionAnswers } from '@/lib/plan-decisions'
import type { PlanDecision } from '@/lib/plan-decisions'

// What the panel says while every decision has the planner's choice picked.
const UNANSWERED =
    "Each has the planner's choice picked. Pick another to answer it: the answer goes with Approve or Ask for changes."

/**
 * A plan's open decisions (`planDecisions`), answered where the plan is read rather than in a round of comments: each
 * its question and its options as a radio group, the planner's choice picked at first and marked so. Picking another
 * option answers the decision, a line that goes with Approve to the implement and with Ask for changes to the planner
 * (`decisionAnswers`); leaving the planner's choice sends nothing. The picks are the caller's state, by decision
 * number, kept on the page alone: while any answers, it holds words not yet sent, which leaving the page asks about.
 * The plan's words are the planner's, so they stay text, their code spans set as code (`InlineCode`).
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
        <section aria-labelledby={id} className="flex flex-col gap-4 border-t px-6 py-4" data-testid="plan-decisions">
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

// One decision: its question, then its options, each its letter and words beside its radio, the planner's marked.
function DecisionChoice({
    decision,
    picked,
    onPick,
}: {
    decision: PlanDecision
    picked: string
    onPick: (letter: string) => void
}) {
    const id = useId()
    return (
        <fieldset className="flex max-w-3xl flex-col gap-2">
            <legend id={`${id}-question`} className="mb-2 text-sm font-medium">
                <InlineCode text={`Decision ${decision.number}: ${decision.question}`} links={false} />
            </legend>
            <RadioGroup value={picked} onValueChange={onPick} aria-labelledby={`${id}-question`}>
                {decision.options.map((option) => (
                    <div key={option.letter} className="flex items-start gap-2">
                        {/* Level with the label's first line, a text-sm line of 20px. */}
                        <RadioGroupItem value={option.letter} id={`${id}-${option.letter}`} className="mt-0.5" />
                        <label htmlFor={`${id}-${option.letter}`} className="text-sm">
                            <span className="font-medium">{option.letter}:</span>{' '}
                            <InlineCode text={option.text} links={false} />
                            {option.letter === decision.chosen && (
                                <span className="text-xs text-muted-foreground"> (the planner&apos;s choice)</span>
                            )}
                        </label>
                    </div>
                ))}
            </RadioGroup>
        </fieldset>
    )
}
