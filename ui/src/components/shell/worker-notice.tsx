import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Megaphone, X } from 'lucide-react'

import { clearNotice, showLoop } from '@/api/mutations'
import { loopQuery } from '@/api/queries'
import type { WorkerNotice } from '@/api/types'
import { LinkedText } from '@/components/linked-text'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { localTime } from '@/lib/time'
import { cn } from '@/lib/utils'

// Where a notice came from, in the words `canopy status` uses.
const CHANNEL: Record<WorkerNotice['channel'], string> = {
    cli: '`canopy notice`',
    web: 'the web UI',
}

/**
 * The operator's notice to workers (`canopy notice`, docs/design §8), above every page for as long as it is in force:
 * what it says, until when runs hear it, and Clear. It is the journal's, so one set from the CLI shows here as the
 * stream sends it, and one that lapses goes the same way. Settings sets one.
 */
export function NoticeBanner() {
    const client = useQueryClient()
    const told = useQuery(loopQuery).data?.notice ?? null
    const clear = useMutation({
        mutationFn: clearNotice,
        onSuccess: (changed) => showLoop(client, changed.loop),
    })
    if (told === null) {
        return null
    }
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
                <p className="text-sm break-words">
                    <span className="font-medium text-status-blocked">Notice to workers: </span>
                    <LinkedText text={told.text} />
                </p>
                <p
                    className="readout text-xs text-muted-foreground"
                    title={`Set at ${localTime(told.since)} from ${CHANNEL[told.channel]}`}
                >
                    Every run dispatched until {localTime(told.lapses_at)} hears it.
                </p>
                <Notice error={clear.error} />
            </div>
            <Button
                variant="ghost"
                size="sm"
                title="Clear the notice: runs dispatched from now on hear none."
                disabled={clear.isPending}
                onClick={() => clear.mutate()}
            >
                <X />
                Clear
            </Button>
        </section>
    )
}
