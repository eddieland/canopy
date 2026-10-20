import { useMutation, useMutationState, useQuery } from '@tanstack/react-query'

import { tickNow } from '@/api/mutations'
import { keys, metaQuery, tickQuery } from '@/api/queries'
import { useLoopDown } from '@/hooks/use-loop-down'

/**
 * Tick now's request, shared by every Tick now on the page through its key, so the header shows the tick it asked for
 * from the click on: `useTickAsked` reads it. Its variables are the latest tick's id when it was asked, or null before
 * any.
 */
export function useTickNow() {
    return useMutation({ mutationKey: keys.tickNow, mutationFn: (_after: number | null) => tickNow() })
}

/**
 * Whether Tick now asked for a tick the loop has not started yet: from the click until a newer tick appears, or the
 * one it waits behind has ended and the next is on its way. The request returns once the loop is asked, and the tick's
 * row lands when its wait next looks, which can be after a poll of the sources: the header shows it starting meanwhile
 * rather than nothing. Never while a tick runs, which shows itself, nor while the loop isn't answering, nor over the
 * mock journal, where no loop runs to start one.
 */
export function useTickAsked(): boolean {
    const tick = useQuery(tickQuery).data?.tick ?? null
    const mock = useQuery(metaQuery).data?.mock ?? false
    const down = useLoopDown().offline
    const asks = useMutationState({
        filters: { mutationKey: keys.tickNow },
        select: (mutation) => ({ status: mutation.state.status, after: mutation.state.variables }),
    })
    const last = asks.at(-1)
    if (last === undefined || mock || down || tick?.status === 'running') {
        return false
    }
    return (last.status === 'pending' || last.status === 'success') && last.after === (tick?.id ?? null)
}
