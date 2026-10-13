import { createFileRoute, redirect } from '@tanstack/react-router'

/** The root path: redirects to the attention list. */
export const Route = createFileRoute('/')({
    beforeLoad: () => {
        redirect({ to: '/attention', replace: true, throw: true })
    },
})
