import { Tip } from '@/components/tip'
import { useClock } from '@/lib/clock'
import { age, localTime, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/**
 * How an age reads, by what it measures (ui/DESIGN.md, "Ages"): `bare` for how long something has stood open (`3m`),
 * `ago` for a moment (`3m ago`), `span` for something that runs (`for 3m`, then `ended 3m ago`).
 */
export type AgeVariant = 'bare' | 'ago' | 'span'

/** An age since one moment: `bare` (the default) or `ago`. */
interface Since {
    /** When it was or began, ISO. */
    at: string
    /** `bare` (the default) or `ago`. */
    variant?: 'bare' | 'ago'
    /** Extra classes, for its place in a row. */
    className?: string
}

/** The age of something that runs: a run, a review, a tick, a chore run. */
interface Span {
    /** Always `span`. */
    variant: 'span'
    /** When it started, ISO. */
    started: string
    /** When it ended, ISO; null while it runs. */
    ended: string | null
    /** Extra classes, for its place in a row. */
    className?: string
}

type AgeProps = Since | Span

/**
 * An age as a readout, in the CLI's largest whole unit, with the local time in a `Tip`, on hover and on the keyboard's
 * focus: `3m`, `3m ago`, or for something that runs `for 3m` and once it ended `ended 3m ago`. The words sit muted
 * beside the fixed-width number.
 */
export function Age(props: AgeProps) {
    const clock = useClock()
    const now = useNow()
    const at = props.variant === 'span' ? (props.ended ?? props.started) : props.at
    const [before, after] = words(props)
    return (
        <Tip fact={localTime(at, clock)}>
            <time dateTime={at} className={cn('text-xs whitespace-nowrap text-muted-foreground', props.className)}>
                {before}
                <span className="readout">{age(at, now)}</span>
                {after}
            </time>
        </Tip>
    )
}

function words(props: AgeProps): [string, string] {
    switch (props.variant) {
        case 'span': {
            return props.ended === null ? ['for ', ''] : ['ended ', ' ago']
        }
        case 'ago': {
            return ['', ' ago']
        }
        case 'bare':
        case undefined: {
            return ['', '']
        }
    }
}
