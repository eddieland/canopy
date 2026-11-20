import { useState } from 'react'

import { AmountField } from '@/components/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { COST_AMOUNT_MAX, COST_OPS, COST_WORDS, costAmountOf, costBoundText } from '@/lib/sessions'
import type { CostBound, CostOp } from '@/lib/sessions'

/** The comparison the control opens on: what cost the most is what a list is most often narrowed to. */
const OPENS_ON: CostOp = 'gte'

/**
 * A list's filter by what each row cost, kept in its page's `?cost=` (`bound`): a comparison, one of four in a
 * segmented control, in words, since `<` and `≤` read alike at a filter's size, and an amount in dollars. The list
 * narrows as the operator types, `onFilter` taking the bound, or undefined while the field holds no amount; a
 * comparison picked before any amount waits for one. Back or a link changing `?cost=` shows the new bound here, as a
 * `FilterField` shows its text.
 */
export function CostFilter({
    bound,
    onFilter,
}: {
    /** The page's validated `?cost=`. */
    bound: CostBound | undefined
    /** Sets the page's `?cost=`. */
    onFilter: (bound: CostBound | undefined) => void
}) {
    const [op, setOp] = useState(bound?.op ?? OPENS_ON)
    const [text, setText] = useState(bound === undefined ? '' : String(bound.usd))
    // What `?cost=` was when the control last looked: a change to anything but what the control holds came from
    // outside it, Back or a link, and shows here.
    const key = bound === undefined ? undefined : costBoundText(bound)
    const [seen, setSeen] = useState(key)
    if (key !== seen) {
        setSeen(key)
        const held = costAmountOf(text)
        if (key !== (held === undefined ? undefined : costBoundText({ op, usd: held }))) {
            setText(bound === undefined ? '' : String(bound.usd))
            setOp(bound?.op ?? op)
        }
    }

    function filter(nextOp: CostOp, nextText: string) {
        const usd = costAmountOf(nextText)
        setOp(nextOp)
        setText(nextText)
        onFilter(usd === undefined ? undefined : { op: nextOp, usd })
    }

    return (
        <fieldset aria-label="Filter by cost" className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">cost</span>
            <ToggleGroup
                type="single"
                value={op}
                // Pressing the comparison that is on would turn it off: one stays on.
                onValueChange={(value) => {
                    const picked = COST_OPS.find((o) => o === value)
                    if (picked !== undefined) {
                        filter(picked, text)
                    }
                }}
                aria-label="How the cost compares"
            >
                {COST_OPS.map((o) => (
                    <ToggleGroupItem key={o} value={o}>
                        {COST_WORDS[o]}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <AmountField
                aria-label="Cost in dollars"
                placeholder="any"
                maxLength={COST_AMOUNT_MAX}
                value={text}
                onAmount={(typed) => filter(op, typed)}
                onClear={() => filter(op, '')}
                clearLabel="Clear the cost"
                onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                        event.currentTarget.blur()
                    }
                }}
                className="w-28"
            />
        </fieldset>
    )
}
