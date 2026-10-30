import { createFileRoute, redirect } from '@tanstack/react-router'

/** Where the worktrees page was before Workspace held it: redirects to it, its state filter kept. */
export const Route = createFileRoute('/worktrees')({
    beforeLoad: () => {
        redirect({ to: '/workspace/worktrees', search: true, replace: true, throw: true })
    },
})
