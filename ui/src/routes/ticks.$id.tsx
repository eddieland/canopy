import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where a tick's page was before Workspace held it: redirects to it. */
export const Route = createFileRoute('/ticks/$id')({
    beforeLoad: ({ params, location }) => {
        redirect({ to: '/workspace/ticks/$id', params, search: true, hash: location.hash, replace: true, throw: true })
    },
})
