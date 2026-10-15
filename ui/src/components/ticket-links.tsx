import { GitBranch, GitPullRequest, Ticket } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { useState } from 'react'

import { LinkOutIcon } from '@/components/link-out-icon'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { addressOf } from '@/lib/links'
import { pullRequestLabel } from '@/lib/pull-request-label'

// A default that is a fresh array on each render would be a new prop each time.
const NONE: readonly never[] = []
// The links shown before `N more`: a ticket across many repositories has a PR and a branch in each, and every one of
// them under the title would push its Work panel out of the window.
const SHOWN = 6

/**
 * A ticket's links out, under its page's title so they are the first thing found: its page in the tracker, then each
 * repository's PR, then its branch in each repository that has a branch link. Past `SHOWN`, the first few and a toggle
 * that opens the rest in place. Renders nothing when there are none.
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
    const [open, setOpen] = useState(false)
    const links: Link[] = [
        ...(tracker
            ? [{ href: tracker, label: addressOf(tracker), icon: Ticket, hint: 'The ticket in the tracker' }]
            : []),
        ...units.flatMap(({ repo, pr_url: href }) => {
            if (!href) {
                return []
            }
            const hint = repo ? `The PR in ${repo}` : 'The PR'
            return [{ href, label: pullRequestLabel(href), icon: GitPullRequest, hint }]
        }),
        ...branches.map((b) => ({
            href: b.href,
            label: addressOf(b.href),
            icon: GitBranch,
            hint: `The branch in ${b.repo}`,
        })),
    ]
    if (links.length === 0) {
        return null
    }
    // One toggle never hides a single link: it would take the room the link does.
    const shown = links.length > SHOWN ? links.slice(0, SHOWN - 1) : links
    const rest = links.slice(shown.length)
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <nav aria-label="Links out" className="mt-2 flex flex-wrap gap-2">
                {shown.map((link) => (
                    <LinkOutButton key={link.href} {...link} />
                ))}
                {rest.length > 0 && (
                    <>
                        <CollapsibleContent asChild>
                            <span className="contents">
                                {rest.map((link) => (
                                    <LinkOutButton key={link.href} {...link} />
                                ))}
                            </span>
                        </CollapsibleContent>
                        <CollapsibleTrigger asChild>
                            <Button variant="ghost" size="sm" className="font-mono text-xs font-normal">
                                {open ? 'fewer' : `${rest.length} more`}
                            </Button>
                        </CollapsibleTrigger>
                    </>
                )}
            </nav>
        </Collapsible>
    )
}

/** A link out: where it goes, what it says, its icon, and what it is on hover. */
interface Link {
    href: string
    label: string
    icon: LucideIcon
    hint: string
}

function LinkOutButton({ href, label, icon, hint }: { href: string; label: string; icon: LucideIcon; hint: string }) {
    return (
        <Button
            asChild
            variant="outline"
            size="sm"
            className="max-w-full gap-1.5 font-mono text-xs font-normal text-accent"
        >
            <a href={href} target="_blank" rel="noreferrer noopener" title={hint}>
                <LinkOutIcon href={href} icon={icon} className="size-4" />
                <span className="truncate">{label}</span>
            </a>
        </Button>
    )
}
