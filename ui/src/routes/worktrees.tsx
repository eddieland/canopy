import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where the worktrees page was before Runs held it: redirects to it, its state filter kept. */
export const Route = createFileRoute('/worktrees')({
    beforeLoad: () => {
        redirect({ to: '/runs/worktrees', search: true, replace: true, throw: true })
    },
})
