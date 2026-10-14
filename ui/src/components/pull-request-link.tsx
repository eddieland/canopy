import { Link } from '@tanstack/react-router'

import { LinkOut } from '@/components/link-out-icon'
import { onGitHub } from '@/lib/links'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { cn } from '@/lib/utils'

/**
 * A PR wherever the UI names one: its name (`org/repo#123`, `pullRequestLabel`) opening its page in canopy, with its
 * runs, reviews, and decisions, then a small icon opening the PR itself in a new tab. The label goes in, the icon out.
 */
export function PullRequestLink({ url, className }: { url: string; className?: string }) {
    const label = pullRequestLabel(url)
    return (
        <span className={cn('inline-flex min-w-0 items-center gap-1 font-mono text-xs', className)}>
            <Link
                to="/pull-requests/pr"
                search={{ url }}
                title={url}
                className="truncate text-accent underline-offset-4 hover:underline"
            >
                {label}
            </Link>
            <LinkOut href={url} label={`${label} on ${onGitHub(url) ? 'GitHub' : 'its host'}`} />
        </span>
    )
}
