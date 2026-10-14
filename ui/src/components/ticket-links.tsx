import { GitBranch, GitPullRequest, Ticket } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { LinkOutIcon } from '@/components/link-out-icon'
import { Button } from '@/components/ui/button'

// A default that is a fresh array on each render would be a new prop each time.
const NONE: readonly never[] = []

/**
 * A ticket's links out, under its page's title so they are the first thing found: its page in the tracker, then each
 * repository's PR, then its branch in each repository that has a branch link. Renders nothing when there are none.
 */
export function TicketLinks({
    tracker,
    units = NONE,
    branches = NONE,
}: {
    /** The ticket's page in the tracker, when `tracker.ticket_url` is set. */
    tracker?: string
    /** The ticket's units; each with a PR gets a link. */
    units?: readonly { repo: string | null; pr_url: string | null }[]
    /** The ticket's branch's page in each repository that has one. */
    branches?: readonly { repo: string; href: string }[]
}) {
    const prs = units.flatMap((u) => (u.pr_url ? [{ repo: u.repo, href: u.pr_url }] : []))
    if (tracker === undefined && prs.length === 0 && branches.length === 0) {
        return null
    }
    return (
        <nav aria-label="Links out" className="mt-2 flex flex-wrap gap-2">
            {tracker && <LinkOut href={tracker} icon={Ticket} hint="The ticket in the tracker" />}
            {prs.map((pr) => (
                <LinkOut
                    key={pr.href}
                    href={pr.href}
                    icon={GitPullRequest}
                    hint={pr.repo ? `The PR in ${pr.repo}` : 'The PR'}
                />
            ))}
            {branches.map((b) => (
                <LinkOut key={b.href} href={b.href} icon={GitBranch} hint={`The branch in ${b.repo}`} />
            ))}
        </nav>
    )
}

function LinkOut({ href, icon, hint }: { href: string; icon: LucideIcon; hint: string }) {
    return (
        <Button
            asChild
            variant="outline"
            size="sm"
            className="max-w-full gap-1.5 font-mono text-xs font-normal text-accent"
        >
            <a href={href} target="_blank" rel="noreferrer noopener" title={hint}>
                <LinkOutIcon href={href} icon={icon} className="size-4" />
                <span className="truncate">{href.replace(/^https:\/\//u, '')}</span>
            </a>
        </Button>
    )
}
