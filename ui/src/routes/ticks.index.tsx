import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where the ticks page was before Runs held it: redirects to it. */
export const Route = createFileRoute('/ticks/')({
    beforeLoad: () => {
        redirect({ to: '/runs/ticks', search: true, replace: true, throw: true })
    },
})
