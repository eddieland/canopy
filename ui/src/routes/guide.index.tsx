import { createFileRoute, redirect } from '@tanstack/react-router'

import { GUIDE } from '@/lib/guide'

/** The guide's root: opens its first page, as a documentation site opens on its introduction. */
export const Route = createFileRoute('/guide/')({
    beforeLoad: () => {
        redirect({ to: '/guide/$page', params: { page: GUIDE[0]?.slug ?? '' }, replace: true, throw: true })
    },
})
