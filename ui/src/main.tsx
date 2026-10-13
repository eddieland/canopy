import './index.css'

import { QueryClientProvider } from '@tanstack/react-query'
import { createRouter, RouterProvider } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { api, writeToken } from '@/api/client'
import { keys } from '@/api/queries'
import { PAGE_SCROLLER } from '@/components/shell/app-shell'
import type { Session } from '@/api/types'
import { basePath } from '@/lib/base'
import { createQueryClient } from '@/lib/query-client'

import { routeTree } from './routeTree.gen'

const queryClient = createQueryClient()
// Every write carries the session's token (DESIGN §22).
api.use(writeToken(() => queryClient.getQueryData<Session>(keys.session)?.token))

const router = createRouter({
    routeTree,
    basepath: basePath || '/',
    context: { queryClient },
    defaultPreload: 'intent',
    // Loaders read the Query cache; the router keeps no cache of its own.
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
    // The page scrolls under the header, not the window (AppShell): a new page starts at its top there too.
    scrollToTopSelectors: [`[data-scroll-restoration-id="${PAGE_SCROLLER}"]`],
})

declare module '@tanstack/react-router' {
    interface Register {
        router: typeof router
    }
}

const root = document.getElementById('root')
if (!root) throw new Error('index.html has no #root')

createRoot(root).render(
    <StrictMode>
        <QueryClientProvider client={queryClient}>
            <RouterProvider router={router} />
        </QueryClientProvider>
    </StrictMode>,
)
