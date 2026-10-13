import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Link } from '@tanstack/react-router'

import { AppShell } from '@/components/shell/app-shell'
import { PageHeader, Panel, Placeholder } from '@/components/panel'

/** What every route's loaders and hooks get from the router. */
export interface RouterContext {
    /** The app's one query client. */
    queryClient: QueryClient
}

/** The root route: every page renders inside the app shell, and a path no route matches gets the not-found page. */
export const Route = createRootRouteWithContext<RouterContext>()({
    component: AppShell,
    notFoundComponent: NotFound,
})

function NotFound() {
    return (
        <>
            <PageHeader root="404" title="Nothing here" />
            <Panel>
                <Placeholder>
                    <Link to="/attention" className="text-accent underline-offset-4 hover:underline">
                        Go to the attention list
                    </Link>
                </Placeholder>
            </Panel>
        </>
    )
}
