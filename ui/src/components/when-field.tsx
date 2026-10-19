import { Age } from '@/components/age'
import { Field } from '@/components/fields'
import { Timestamp } from '@/components/timestamp'
import { useClock } from '@/lib/clock'
import { endStamp, lasted } from '@/lib/time'

/**
 * A detail page's `when` field, for something that runs (a run, a tick, a chore run): when it started, then once it
 * ended, when, the time alone on the same day, and how long it took, `Oct 8 06:30 → 06:59 · 29m`; then its `span`
 * age, `for 3m` while it runs and `ended 9d ago` after.
 */
export function WhenField({ started, ended }: { started: string; ended: string | null }) {
    const clock = useClock()
    return (
        <Field label="when" mono>
            <span className="flex flex-wrap items-baseline gap-x-2">
                <span className="whitespace-nowrap">
                    <Timestamp at={started} />
                    {ended !== null && (
                        <>
                            <span className="text-muted-foreground"> → </span>
                            <time dateTime={ended} title={ended} className="readout text-xs">
                                {endStamp(started, ended, clock)}
                            </time>
                            <span className="text-muted-foreground"> · </span>
                            <span className="readout" title="how long it ran">
                                {lasted(started, ended)}
                            </span>
                        </>
                    )}
                </span>
                <Age variant="span" started={started} ended={ended} />
            </span>
        </Field>
    )
}
