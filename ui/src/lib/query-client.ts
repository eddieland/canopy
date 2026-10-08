import { keepPreviousData, MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import { keys } from '@/api/queries'
import type { Session } from '@/api/types'

const SIGNED_OUT: Session = { signed_in: false, token: null }

/**
 * The app's one QueryClient.
 *
 * Freshness comes from the event stream (useLiveUpdates), not from refetching: data stays fresh for a minute, and
 * focus and reconnect refetches are off. `keepPreviousData` keeps the last result on screen while a query with a new
 * key loads, so a refetch never blanks content; components show a skeleton only when there is no data at all.
 *
 * A 401 anywhere means the session is gone (a new secret, or 30 days passed): the shell shows the sign-in page.
 */
export function createQueryClient(): QueryClient {
    const signedOut = (error: unknown) => {
        if (error instanceof ApiError && error.status === 401) client.setQueryData(keys.session, SIGNED_OUT)
    }
    const client: QueryClient = new QueryClient({
        queryCache: new QueryCache({ onError: signedOut }),
        mutationCache: new MutationCache({ onError: signedOut }),
        defaultOptions: {
            queries: {
                staleTime: 60_000,
                gcTime: 10 * 60_000,
                refetchOnWindowFocus: false,
                refetchOnReconnect: false,
                // A refusal or a missing session will not change on a retry.
                retry: (failures, error) => failures < 1 && !(error instanceof ApiError && error.status < 500),
                placeholderData: keepPreviousData,
            },
        },
    })
    return client
}
