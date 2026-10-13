import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** A PR that opens its page in canopy, its runs, reviews, and decisions: by default its URL without `https://`. */
export function PullRequestLink({
    url,
    className,
    children,
}: {
    url: string
    className?: string
    children?: ReactNode
}) {
    return (
        <Link
            to="/pull-requests/pr"
            search={{ url }}
            title={url}
            className={cn('font-mono text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            {children ?? url.replace(/^https:\/\//u, '')}
        </Link>
    )
}
