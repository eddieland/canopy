import { createFileRoute, redirect } from '@tanstack/react-router'

/** The root path: redirects to the attention list. */
export const Route = createFileRoute('/')({
    beforeLoad: () => {
        throw redirect({ to: '/attention', replace: true })
    },
})
