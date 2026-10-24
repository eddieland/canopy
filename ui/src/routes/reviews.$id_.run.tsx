import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where a review's run was before Pull requests held it: redirects to it. */
export const Route = createFileRoute('/reviews/$id_/run')({
    beforeLoad: ({ params, location }) => {
        redirect({
            to: '/pull-requests/reviews/$id/run',
            params,
            search: true,
            hash: location.hash,
            replace: true,
            throw: true,
        })
    },
})
