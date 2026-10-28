import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where a review's page was before Pull requests held it: redirects to it, the finding it points at kept. */
export const Route = createFileRoute('/reviews/$id')({
    beforeLoad: ({ params, location }) => {
        redirect({
            to: '/pull-requests/reviews/$id',
            params,
            search: true,
            hash: location.hash,
            replace: true,
            throw: true,
        })
    },
})
