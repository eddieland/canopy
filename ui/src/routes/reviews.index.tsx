import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where the reviews page was before Pull requests held it: redirects to it, its filter kept. */
export const Route = createFileRoute('/reviews/')({
    beforeLoad: () => {
        redirect({ to: '/pull-requests/reviews', search: true, replace: true, throw: true })
    },
})
