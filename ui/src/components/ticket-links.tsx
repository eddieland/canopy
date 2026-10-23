import { ChevronDown, GitBranch, GitPullRequest, Ticket } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { LinkOutIcon } from '@/components/link-out-icon'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { addressOf, onGitHub } from '@/lib/links'
import { pullRequestLabel } from '@/lib/pull-request-label'

// A default that is a fresh array on each render would be a new prop each time.
const NONE: readonly never[] = []
// A link out's button: an `sm` outline button, its label in the accent's monospace, since it names an address.
const LINK_OUT = 'max-w-full gap-1.5 font-mono text-accent'

/**
 * A ticket's links out, under its page's title so they are the first thing found: its page in the tracker, then its
 * PRs, then its branches. A kind with one link is a button; with more, one per repository, a button that opens them
 * as a menu (`3 PRs`), so a ticket across many repositories keeps one line here. Renders nothing when there are none.
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
    const prs: Link[] = units.flatMap(({ repo, pr_url: href }) => {
        if (!href) {
            return []
        }
        const label = pullRequestLabel(href)
        return [{ href, label, name: label, icon: GitPullRequest, hint: repo ? `The PR in ${repo}` : 'The PR' }]
    })
    // In a menu a branch goes by its repository: the branch is the ticket's in every one.
    const branchLinks: Link[] = branches.map((b) => ({
        href: b.href,
        label: addressOf(b.href),
        name: b.repo,
        icon: GitBranch,
        hint: `The branch in ${b.repo}`,
    }))
    if (tracker === undefined && prs.length === 0 && branchLinks.length === 0) {
        return null
    }
    return (
        <nav aria-label="Links out" className="mt-2 flex flex-wrap gap-2">
            {tracker && (
                <LinkOutButton
                    href={tracker}
                    label={addressOf(tracker)}
                    icon={Ticket}
                    hint="The ticket in the tracker"
                />
            )}
            <LinkGroup links={prs} icon={GitPullRequest} many="PRs" />
            <LinkGroup links={branchLinks} icon={GitBranch} many="branches" />
        </nav>
    )
}

/**
 * A PR's link out, under the title of a page about it: a PR's own page, and each of its reviews'. The title names the
 * PR, so the button says where it goes (`on GitHub`) rather than naming it again.
 */
export function PullRequestLinksOut({ url }: { url: string }) {
    return (
        <nav aria-label="Links out" className="mt-2 flex flex-wrap gap-2">
            <LinkOutButton
                href={url}
                label={onGitHub(url) ? 'on GitHub' : addressOf(url)}
                icon={GitPullRequest}
                hint="The PR"
            />
        </nav>
    )
}

/** A link out, as a button or an item in its kind's menu. */
interface Link {
    /** Where it goes. */
    href: string
    /** What its button says: a PR's name, or the address. */
    label: string
    /** What its item in a menu says, beside its kin. */
    name: string
    /** Its icon off GitHub. */
    icon: LucideIcon
    /** What it opens, on hover. */
    hint: string
}

/** One kind of link: nothing for none, its button for one, and a button opening a menu of all of them for more. */
function LinkGroup({ links, icon, many }: { links: Link[]; icon: LucideIcon; many: string }) {
    const [only] = links
    if (only === undefined) {
        return null
    }
    if (links.length === 1) {
        return <LinkOutButton {...only} />
    }
    const Icon = icon
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="outline"
                    size="sm"
                    className={LINK_OUT}
                    title={`The ticket's ${links.length} ${many}, one per repository`}
                >
                    <Icon aria-hidden className="size-4" />
                    {links.length} {many}
                    <ChevronDown aria-hidden />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-w-[min(36rem,var(--radix-popper-available-width))]">
                {links.map((link) => (
                    <DropdownMenuItem key={link.href} asChild>
                        <a
                            href={link.href}
                            target="_blank"
                            rel="noreferrer noopener"
                            title={link.label === link.name ? link.hint : `${link.hint}: ${link.label}`}
                            className="font-mono text-xs text-accent"
                        >
                            <LinkOutIcon href={link.href} icon={link.icon} className="size-4" />
                            <span className="truncate">{link.name}</span>
                        </a>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

/**
 * One link out as a page's header shows it (ui/DESIGN.md, "A link out"): an outline button in the accent's monospace,
 * what it opens as its one icon first (GitHub's mark for github.com), then its label, opening in a new tab. `hint` says
 * on hover what it opens.
 */
export function LinkOutButton({
    href,
    label,
    icon,
    hint,
}: {
    /** Where it goes. */
    href: string
    /** What it says: an address, a PR's name, or where it goes. */
    label: string
    /** What it opens, shown unless `href` is on github.com. */
    icon: LucideIcon
    /** What it opens, in words, on hover. */
    hint: string
}) {
    return (
        <Button asChild variant="outline" size="sm" className={LINK_OUT}>
            <a href={href} target="_blank" rel="noreferrer noopener" title={hint}>
                <LinkOutIcon href={href} icon={icon} className="size-4" />
                <span className="truncate">{label}</span>
            </a>
        </Button>
    )
}
