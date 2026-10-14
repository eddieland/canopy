import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
    Activity,
    CalendarClock,
    FileSearch,
    FolderTree,
    GitPullRequest,
    History,
    Inbox,
    MessagesSquare,
    SlidersHorizontal,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { attentionQuery } from '@/api/queries'
import { useSection } from '@/hooks/use-section'
import { countBySeverity } from '@/lib/attention'
import type { Severity } from '@/lib/attention'
import { SECTION_FILL, SECTION_LABEL, SECTION_TEXT, SECTION_TINT } from '@/lib/sections'
import type { Section } from '@/lib/sections'
import { cn } from '@/lib/utils'

// Each item's hint is its tooltip: what the page holds, for an operator who does not know it yet.
const ITEMS: { to: Section; icon: LucideIcon; hint: string }[] = [
    { to: '/attention', icon: Inbox, hint: 'What needs you, most severe first' },
    { to: '/runs', icon: Activity, hint: 'Workers running now, then the ones that ended last' },
    {
        to: '/worktrees',
        icon: FolderTree,
        hint: "Each repository's pool: its slots and what holds them",
    },
    {
        to: '/tickets',
        icon: MessagesSquare,
        hint: 'Every ticket canopy has worked, and a form to start one',
    },
    {
        to: '/pull-requests',
        icon: GitPullRequest,
        hint: "Every PR canopy knows: the loop's own and the ones it reviewed, with their runs and reviews",
    },
    {
        to: '/reviews',
        icon: FileSearch,
        hint: 'PR reviews canopy keeps instead of posting, with findings on the diff',
    },
    { to: '/chores', icon: CalendarClock, hint: 'Scheduled chores, their runs, and their findings' },
    { to: '/ticks', icon: History, hint: "The overseer's latest ticks and what each decided" },
    {
        to: '/settings',
        icon: SlidersHorizontal,
        hint: 'The theme, the fun, the send key, and the session',
    },
]

/**
 * The side navigation. Each item's icon is in its section's color. The active item is marked by one highlight, a tint
 * and a hairline in that color, which slides to the item a navigation lands on and takes on its color as it goes; a
 * ticket's page keeps Tickets active, a PR's Pull requests, a review's Reviews, a chore's Chores, and a tick's Ticks.
 * Attention shows how many items it lists, on every page, split as its counter splits them. Hovering an item says what
 * its page holds.
 */
export function Nav() {
    const attention = useQuery(attentionQuery)
    const counts = attention.data === undefined ? undefined : countBySeverity(attention.data)
    const section = useSection()
    const active = ITEMS.findIndex(({ to }) => to === section)
    // With no section active the highlight is hidden; it keeps a color so it fades rather than flashes.
    const tone = section ?? '/attention'
    return (
        <nav aria-label="Main" className="relative flex flex-col gap-0.5 p-2">
            <span
                aria-hidden
                data-testid="nav-highlight"
                className={cn(
                    'absolute inset-x-2 top-2 h-8 rounded-sm',
                    SECTION_TINT[tone],
                    'motion-safe:transition-[translate,opacity,background-color] motion-safe:duration-300',
                    'motion-safe:ease-[cubic-bezier(0.2,0,0,1)]',
                    active === -1 && 'opacity-0',
                )}
                // Items are h-8 apart by gap-0.5: 2.125rem from one to the next.
                style={{ translate: `0 ${Math.max(active, 0) * 2.125}rem` }}
            >
                <span
                    className={cn(
                        'absolute inset-y-1.5 left-0 w-0.5 rounded-full',
                        SECTION_FILL[tone],
                        'motion-safe:transition-colors motion-safe:duration-300',
                    )}
                />
            </span>
            {ITEMS.map(({ to, icon: Icon, hint }) => (
                <Link
                    key={to}
                    to={to}
                    title={hint}
                    activeOptions={{ exact: false }}
                    className={cn(
                        'group relative flex h-8 items-center gap-2.5 rounded-sm px-2.5 text-sm text-muted-foreground',
                        'transition-colors hover:bg-surface-raised hover:text-foreground',
                        'data-[status=active]:text-foreground data-[status=active]:hover:bg-transparent',
                    )}
                >
                    <Icon
                        className={cn(
                            'size-4 transition-transform group-hover:-rotate-6 motion-reduce:transition-none',
                            SECTION_TEXT[to],
                        )}
                    />
                    {SECTION_LABEL[to]}
                    {to === '/attention' && counts !== undefined && <AttentionCount counts={counts} />}
                </Link>
            ))}
        </nav>
    )
}

/**
 * The attention list's count beside its nav item: what is broken in the failure color, what waits on the operator's
 * answer in theirs, and the rest muted, each shown only when there is one. Not the section's rose, which is too near
 * the failure color to tell apart at this size. Color alone does not say which number is which, so the numbers are
 * also said in words, on hover and to a screen reader (`1 broken, 1 waiting on you, 3 other`).
 */
function AttentionCount({ counts }: { counts: Record<Severity, number> }) {
    const parts = [
        { kind: 'failed', label: 'broken', count: counts.failed, tone: 'text-status-failed' },
        { kind: 'waiting', label: 'waiting on you', count: counts.waiting, tone: 'text-status-blocked' },
        { kind: 'other', label: 'other', count: counts.other + counts.finding, tone: 'text-muted-foreground' },
    ].filter(({ count }) => count > 0)
    if (parts.length === 0) {
        return null
    }
    const said = parts.map(({ count, label }) => `${count} ${label}`).join(', ')
    return (
        <span className="ml-auto flex gap-1.5 readout text-xs" title={said} data-testid="nav-attention-count">
            {parts.map(({ kind, count, tone }) => (
                <span key={kind} aria-hidden className={tone} data-testid={`nav-attention-${kind}`}>
                    {count}
                </span>
            ))}
            <span className="sr-only">{said}</span>
        </span>
    )
}
