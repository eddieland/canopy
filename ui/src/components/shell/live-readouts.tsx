import { useQuery } from '@tanstack/react-query'

import { metaQuery } from '@/api/queries'
import type { StreamStatus } from '@/hooks/use-event-stream'
import { cn } from '@/lib/utils'

const STREAM_LABEL: Record<StreamStatus, string> = {
    connecting: 'connecting',
    open: 'live',
    reconnecting: 'reconnecting',
    closed: 'offline',
}

/** The header's readout: the stream's state, and `mock` over fixture data. The counters are the attention page's. */
export function LiveReadouts({ stream }: { stream: StreamStatus }) {
    const meta = useQuery(metaQuery)
    return (
        <div className="flex items-center gap-5" data-testid="live-readouts">
            <span
                className={cn(
                    'readout inline-flex w-28 items-center justify-end gap-1.5 text-[0.6875rem] uppercase',
                    stream === 'open' ? 'text-accent' : 'text-muted-foreground',
                )}
                data-testid="stream-status"
                data-status={stream}
            >
                {meta.data?.mock && <span className="rounded-sm border px-1 text-muted-foreground">mock</span>}
                {STREAM_LABEL[stream]}
            </span>
        </div>
    )
}
