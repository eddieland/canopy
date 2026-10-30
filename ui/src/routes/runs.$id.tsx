import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where a run's page was before Workspace held it: redirects to it. */
export const Route = createFileRoute('/runs/$id')({
    beforeLoad: ({ params, location }) => {
        redirect({ to: '/workspace/runs/$id', params, search: true, hash: location.hash, replace: true, throw: true })
    },
})
