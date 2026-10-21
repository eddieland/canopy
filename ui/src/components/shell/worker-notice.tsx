import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Megaphone, MegaphoneOff, Pencil, TimerReset } from 'lucide-react'
import { useState } from 'react'

import { clearNotice, setNotice, showLoop } from '@/api/mutations'
import { loopQuery } from '@/api/queries'
import type { WorkerNotice } from '@/api/types'
import { LinkedText } from '@/components/linked-text'
import { Notice } from '@/components/notice'
import { NoticeForm } from '@/components/notice-form'
import { Button } from '@/components/ui/button'
import { useClock } from '@/lib/clock'
import { durationText, minutesSetFor } from '@/lib/notice-time'
import { localTime } from '@/lib/time'
import { cn } from '@/lib/utils'

// Where a notice came from, in the words `canopy status` uses.
const CHANNEL: Record<WorkerNotice['channel'], string> = {
    cli: '`canopy notice`',
    web: 'the web UI',
}

/**
 * The operator's notice to workers (`canopy notice`, docs/design §8), above every page for as long as it is in force:
 * what it says, until when runs hear it, and Edit, Renew, and Clear. Edit opens its words in place, its time kept
 * unless another is picked; Renew sets it again for as long as it was set for, from now. Both replace it, as
 * `canopy notice` does. It is the journal's, so one set from the CLI shows here as the stream sends it, and one that
 * lapses goes the same way. Settings sets one.
 */
export function NoticeBanner() {
    const clock = useClock()
    const client = useQueryClient()
    const told = useQuery(loopQuery).data?.notice ?? null
    // The notice being edited, by when it was set: one that lapses, is cleared, or is replaced from elsewhere ends the
    // edit, so the next notice never arrives with its form already open.
    const [editingSince, setEditingSince] = useState<string | null>(null)
    const clear = useMutation({
        mutationFn: clearNotice,
        onSuccess: (changed) => showLoop(client, changed.loop),
    })
    const renew = useMutation({
        mutationFn: (held: WorkerNotice) => setNotice(held.text, minutesSetFor(held.since, held.lapses_at)),
        onSuccess: (changed) => showLoop(client, changed.loop),
    })
    if (told === null) {
        return null
    }
    const editing = editingSince === told.since
    const lasts = durationText(minutesSetFor(told.since, told.lapses_at))
    const pending = clear.isPending || renew.isPending
    return (
        <section
            aria-label="Notice to workers"
            data-testid="worker-notice"
            className={cn(
                'mx-auto mb-6 flex max-w-[112rem] items-start gap-3 rounded-md border px-3 py-2',
                'border-status-blocked/40 bg-status-blocked/8',
            )}
        >
            <Megaphone aria-hidden className="mt-0.5 size-4 shrink-0 text-status-blocked" />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                {editing ? (
                    <NoticeForm
                        initial={told.text}
                        until={told.lapses_at}
                        submit="Save notice"
                        label="The notice's words"
                        testId="notice-edit"
                        onSet={() => setEditingSince(null)}
                        onCancel={() => setEditingSince(null)}
                    >
                        <p className="text-sm font-medium text-status-blocked">Edit the notice to workers</p>
                    </NoticeForm>
                ) : (
                    <>
                        <p className="text-sm break-words">
                            <span className="font-medium text-status-blocked">Notice to workers: </span>
                            <LinkedText text={told.text} />
                        </p>
                        <p
                            className="readout text-xs text-muted-foreground"
                            title={`Set at ${localTime(told.since, clock)} from ${CHANNEL[told.channel]}`}
                        >
                            Every run dispatched until {localTime(told.lapses_at, clock)} hears it.
                        </p>
                        <Notice error={clear.error ?? renew.error} />
                    </>
                )}
            </div>
            {editing ? null : (
                <div className="flex shrink-0 items-center gap-1">
                    <Button
                        variant="ghost"
                        size="sm"
                        title="Edit the notice's words or how long it lasts."
                        disabled={pending}
                        onClick={() => {
                            clear.reset()
                            renew.reset()
                            setEditingSince(told.since)
                        }}
                    >
                        <Pencil />
                        Edit
                    </Button>
                    <Button
                        variant="ghost"
                        size="sm"
                        title={`Renew the notice for ${lasts}, as long as it was set for, from now.`}
                        disabled={pending}
                        onClick={() => {
                            clear.reset()
                            renew.mutate(told)
                        }}
                    >
                        <TimerReset />
                        Renew
                    </Button>
                    <Button
                        variant="ghost"
                        size="sm"
                        title="Clear the notice: runs dispatched from now on hear none."
                        disabled={pending}
                        onClick={() => {
                            renew.reset()
                            clear.mutate()
                        }}
                    >
                        <MegaphoneOff />
                        Clear
                    </Button>
                </div>
            )}
        </section>
    )
}
