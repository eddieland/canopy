import type { Transcript } from '@/api/types'
import { Field } from '@/components/fields'
import { None } from '@/components/none'
import { Skeleton } from '@/components/ui/skeleton'
import { useClock } from '@/lib/clock'
import { localTime } from '@/lib/time'
import { elapsed, endedOn, startOf } from '@/lib/transcript'
import { cn } from '@/lib/utils'

// The statuses a run or chore run ends on when its session went wrong. Not `timeout`, `unpushed`, or `stopped`: the
// clock, a branch, or the operator ended those, and the transcript's last error would only look like the cause.
const ENDED_BADLY: ReadonlySet<string> = new Set(['failed', 'crashed', 'unknown'])

/**
 * A Run panel's `ended on` field, for a run or chore run that ended `failed`, `crashed`, or `unknown`: what its
 * session ended on (`endedOn`), its time, its name or tool, and its first line in `status-failed`, a button that shows
 * its row in the transcript (`onShow`, by its place in the entries). Nothing for any other status; a skeleton while
 * the transcript is read, so the fields under it never move. A transcript cut short may lack the log's end, which its
 * hover says. Agent output, rendered as text.
 */
export function EndedOnField({
    status,
    transcript,
    onShow,
}: {
    status: string
    transcript: Transcript | undefined
    onShow: (i: number) => void
}) {
    const clock = useClock()
    if (!ENDED_BADLY.has(status)) {
        return null
    }
    if (transcript === undefined) {
        return (
            <Field label="ended on" mono>
                <Skeleton className="h-4 w-72 max-w-full" />
            </Field>
        )
    }
    const ended = endedOn(transcript.entries)
    if (ended === null) {
        return (
            <Field label="ended on" mono>
                <None reason="no runtime error or failed call in its transcript" />
            </Field>
        )
    }
    const { i, entry, line } = ended
    const name = entry.kind === 'error' ? entry.name : entry.tool
    return (
        <Field label="ended on" mono>
            <button
                type="button"
                onClick={() => onShow(i)}
                title={
                    transcript.truncated
                        ? 'Show it in the transcript, which is cut: the log may end on a later one'
                        : 'Show it in the transcript'
                }
                className={cn(
                    'flex max-w-full min-w-0 items-baseline gap-2 rounded-sm text-left text-status-failed',
                    'underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50',
                )}
            >
                {entry.at !== null && (
                    <span className="readout shrink-0" title={localTime(entry.at, clock)}>
                        {elapsed(entry.at, startOf(transcript.entries))}
                    </span>
                )}
                <span className="shrink-0">{name}</span>
                {line !== '' && (
                    <span className="truncate" title={line}>
                        {line}
                    </span>
                )}
            </button>
        </Field>
    )
}
