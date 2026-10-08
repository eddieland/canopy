import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Link } from '@tanstack/react-router'

import { AppShell } from '@/components/shell/app-shell'
import { PageHeader, Panel, Placeholder } from '@/components/panel'

export interface RouterContext {
    queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
    component: AppShell,
    notFoundComponent: NotFound,
})

function NotFound() {
    return (
        <>
            <PageHeader label="404" title="Nothing here" />
            <Panel>
                <Placeholder>
                    <Link to="/sessions" className="text-accent underline-offset-4 hover:underline">
                        Go to sessions
                    </Link>
                </Placeholder>
            </Panel>
        </>
    )
}
