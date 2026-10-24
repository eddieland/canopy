import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where the spend page was before Reports held it: redirects to it, its window and kind filters kept. */
export const Route = createFileRoute('/spend')({
    beforeLoad: () => {
        redirect({ to: '/reports/spend', search: true, replace: true, throw: true })
    },
})
