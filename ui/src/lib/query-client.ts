import { keepPreviousData, QueryClient } from '@tanstack/react-query'

/**
 * The app's one QueryClient.
 *
 * Freshness comes from the event stream (useLiveUpdates), not from refetching: data stays fresh for a minute, and
 * focus and reconnect refetches are off. `keepPreviousData` keeps the last result on screen while a query with a new
 * key loads, so a refetch never blanks content; components show a skeleton only when there is no data at all.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        gcTime: 10 * 60_000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        retry: 1,
        placeholderData: keepPreviousData,
      },
    },
  })
}
