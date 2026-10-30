import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where the runs page was before Workspace held it: redirects to it, its filters kept. */
export const Route = createFileRoute('/runs/')({
    beforeLoad: () => {
        redirect({ to: '/workspace/runs', search: true, replace: true, throw: true })
    },
})
