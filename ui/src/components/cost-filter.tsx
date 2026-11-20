import { X } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { COST_AMOUNT_MAX, COST_OPS, COST_SIGN, COST_WORDS, costAmountOf, costBoundText } from '@/lib/sessions'
import type { CostBound, CostOp } from '@/lib/sessions'
import { cn } from '@/lib/utils'

/** The comparison the control opens on: what cost the most is what a list is most often narrowed to. */
const OPENS_ON: CostOp = 'gte'

/**
 * A list's filter by what each row cost, kept in its page's `?cost=` (`bound`): a comparison, one of four in a
 * segmented control, and an amount in dollars. The list narrows as the operator types, `onFilter` taking the bound, or
 * undefined while the field holds no amount; a comparison picked before any amount waits for one. Back or a link
 * changing `?cost=` shows the new bound here, as a `FilterField` shows its text.
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

    const invalid = text.trim() !== '' && costAmountOf(text) === undefined
    return (
        <fieldset aria-label="Filter by cost" className="flex min-w-0 items-center gap-2">
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
                    <ToggleGroupItem key={o} value={o} aria-label={COST_WORDS[o]} title={COST_WORDS[o]}>
                        <span aria-hidden="true" className="font-mono">
                            {COST_SIGN[o]}
                        </span>
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <div
                className={cn(
                    'flex h-8 w-28 items-center gap-1 rounded-md border border-control bg-surface-raised px-2.5',
                    'focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50',
                    invalid && 'border-status-failed focus-within:ring-status-failed/30',
                )}
            >
                <span aria-hidden="true" className="text-sm text-muted-foreground">
                    $
                </span>
                <input
                    type="text"
                    inputMode="decimal"
                    aria-label="Cost in dollars"
                    aria-invalid={invalid || undefined}
                    placeholder="any"
                    maxLength={COST_AMOUNT_MAX}
                    value={text}
                    onChange={(event) => filter(op, event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === 'Escape') {
                            event.currentTarget.blur()
                        }
                    }}
                    className={cn(
                        'min-w-0 flex-1 bg-transparent readout text-sm text-foreground outline-none',
                        'placeholder:text-muted-foreground',
                    )}
                />
                {text !== '' && (
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label="Clear the cost"
                        onClick={() => filter(op, '')}
                        className="hover:bg-muted"
                    >
                        <X aria-hidden />
                    </Button>
                )}
            </div>
        </fieldset>
    )
}
