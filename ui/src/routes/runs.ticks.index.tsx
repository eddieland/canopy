import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where the ticks page was before Workspace held it: redirects to it. */
export const Route = createFileRoute('/runs/ticks/')({
    beforeLoad: () => {
        redirect({ to: '/workspace/ticks', search: true, replace: true, throw: true })
    },
})
