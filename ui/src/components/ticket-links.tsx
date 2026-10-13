import { ExternalLink, GitPullRequest, type LucideIcon, Ticket } from 'lucide-react'

import { Button } from '@/components/ui/button'

/**
 * A ticket's links out, under its page's title so they are the first thing found: its page in the tracker, then each
 * repository's PR. Renders nothing when there is neither.
 */
export function TicketLinks({
    tracker,
    units = [],
}: {
    /** The ticket's page in the tracker, when `tracker.ticket_url` is set. */
    tracker?: string
    /** The ticket's units; each with a PR gets a link. */
    units?: { repo: string | null; pr_url: string | null }[]
}) {
    const prs = units.flatMap((u) => (u.pr_url ? [{ repo: u.repo, href: u.pr_url }] : []))
    if (tracker === undefined && prs.length === 0) return null
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
        </nav>
    )
}

function LinkOut({ href, icon: Icon, hint }: { href: string; icon: LucideIcon; hint: string }) {
    return (
        <Button
            asChild
            variant="outline"
            size="sm"
            className="max-w-full gap-1.5 font-mono text-xs font-normal text-accent"
        >
            <a href={href} target="_blank" rel="noreferrer noopener" title={hint}>
                <Icon aria-hidden />
                <span className="truncate">{href.replace(/^https:\/\//, '')}</span>
                <ExternalLink aria-hidden className="size-3" />
            </a>
        </Button>
    )
}
