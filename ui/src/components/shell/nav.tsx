import { useQuery } from '@tanstack/react-query'
import { Link, useMatchRoute } from '@tanstack/react-router'
import {
    Activity,
    Brain,
    CalendarClock,
    ChartColumn,
    GitPullRequest,
    Inbox,
    MessagesSquare,
    Sprout,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Fragment } from 'react'
import type { CSSProperties } from 'react'

import { loopQuery, reviewsQuery } from '@/api/queries'
import type { ReviewSummary } from '@/api/types'
import { useAttention } from '@/hooks/use-attention'
import { useSection } from '@/hooks/use-section'
import { breakdown, breakdownText, countBySeverity } from '@/lib/attention'
import type { BreakdownPart, Severity } from '@/lib/attention'
import { counted } from '@/lib/descriptions'
import { REPORT_PAGES } from '@/lib/report-pages'
import { verdictTone } from '@/lib/reviews'
import { SECTION_FILL, SECTION_LABEL, SECTION_TEXT, SECTION_TINT } from '@/lib/sections'
import type { Section } from '@/lib/sections'
import { unseenOf, unseenText, worstOf } from '@/lib/seen-reviews'
import { cn } from '@/lib/utils'

// Each part of the attention count's color: broken in the failure color, waiting on the operator's answer in theirs.
const TONE: Record<BreakdownPart['kind'], string> = {
    failed: 'text-status-failed',
    waiting: 'text-status-blocked',
    other: 'text-muted-foreground',
}

// A page under a section, which opens under its item while the section is shown.
interface SubPage {
    to:
        | '/workspace/runs'
        | '/workspace/ticks'
        | '/workspace/worktrees'
        | '/pull-requests/reviews'
        | '/reports/spend'
        | '/reports/checklist'
        | '/reports/health'
        | '/reports/ci'
        | '/reports/reviews'
        | '/reports/plans'
    label: string
    hint: string
}

// In `SECTIONS` order, but for Settings, which the rail's foot opens. Each item's hint is its tooltip: what the page
// holds, for an operator who does not know it yet; `pages` are the pages under it, in the order their parent's
// description links them.
const ITEMS: { to: Section; icon: LucideIcon; hint: string; pages?: SubPage[] }[] = [
    { to: '/attention', icon: Inbox, hint: 'What needs you, most severe first' },
    {
        to: '/tickets',
        icon: MessagesSquare,
        hint: 'Every ticket canopy has worked, and a form to start one',
    },
    {
        to: '/tasks',
        icon: Sprout,
        hint: 'One-off work you handed canopy in your own words, about no ticket, and a form to submit one',
    },
    {
        to: '/pull-requests',
        icon: GitPullRequest,
        hint: "Every PR canopy knows, the loop's own and the ones it reviewed, and canopy's reviews of them",
        pages: [
            {
                to: '/pull-requests/reviews',
                label: 'Reviews',
                hint: "canopy's reviews of PRs, newest first, each finding on its line of the diff",
            },
        ],
    },
    {
        to: '/workspace',
        icon: Activity,
        hint:
            "What the loop does in the workspace: its runs, the overseer's ticks, and each repository's pool of " +
            'worktrees',
        pages: [
            {
                to: '/workspace/runs',
                label: 'Runs',
                hint: 'Workers running now, then the ones that ended last: on tickets, PRs, chores, and tasks',
            },
            {
                to: '/workspace/ticks',
                label: 'Ticks',
                hint: "The overseer's latest ticks: what each found, what it cost, and what it decided",
            },
            {
                to: '/workspace/worktrees',
                label: 'Worktrees',
                hint: "Each repository's pool of worktrees, and what holds them",
            },
        ],
    },
    { to: '/chores', icon: CalendarClock, hint: 'Scheduled chores, their runs, and their findings' },
    {
        to: '/reports',
        icon: ChartColumn,
        hint:
            'What canopy cost and got done month by month, what agent runs cost each day and how they ended, ' +
            'how workers answered your checklists, which checks fail, who reviews, and how plans were approved',
        pages: [...REPORT_PAGES],
    },
    {
        to: '/memory',
        icon: Brain,
        hint: 'What workers remember: the ticket notes and lessons, and which runs read them',
    },
]

// The active item's label and icon, in the ink a palette that draws its highlight as a block sets (`--nav-on-ink`),
// else in its section's color, shaded where it would not read on its tint (`--nav-label-*` in `tokens.css`). Written
// out, so Tailwind finds each.
const SECTION_ACTIVE_INK: Record<Section, string> = {
    '/attention': 'data-[status=active]:text-[color:var(--nav-on-ink,var(--nav-label-attention))]',
    '/workspace': 'data-[status=active]:text-[color:var(--nav-on-ink,var(--nav-label-workspace))]',
    '/tickets': 'data-[status=active]:text-[color:var(--nav-on-ink,var(--nav-label-tickets))]',
    '/tasks': 'data-[status=active]:text-[color:var(--nav-on-ink,var(--nav-label-tasks))]',
    '/pull-requests': 'data-[status=active]:text-[color:var(--nav-on-ink,var(--nav-label-pull-requests))]',
    '/chores': 'data-[status=active]:text-[color:var(--nav-on-ink,var(--nav-label-chores))]',
    '/reports': 'data-[status=active]:text-[color:var(--nav-on-ink,var(--nav-label-reports))]',
    '/memory': 'data-[status=active]:text-[color:var(--nav-on-ink,var(--nav-label-memory))]',
    '/settings': 'data-[status=active]:text-[color:var(--nav-on-ink,var(--nav-label-settings))]',
}

/**
 * The side navigation. Each item's icon is in its section's color. The active item is marked by one highlight, a tint
 * and a bar down its left edge in that color, which slides to the item a navigation lands on and takes on its color as
 * it goes, and its label is in that color too. A palette may draw the highlight as a solid block instead, inking the
 * active item in the canvas's color, drop the bar, or light the active icon (`--nav-block`, `--nav-hairline`,
 * `--nav-on-ink`, `--nav-on-glow` in `tokens.css`); a ticket's page keeps Tickets active, a PR's Pull requests, a
 * chore's Chores, and a run's Runs, under Workspace.
 * While the section shown has pages under it (Workspace: Runs, Ticks, and Worktrees; Pull requests: Reviews; Reports:
 * Spend, Checklist, and Health), they open under its item, indented to its label, on a hairline in its color;
 * elsewhere they stay folded. On one of them, or a page under it, such as a tick's, the highlight is on that page's
 * item, and the section's label stays in `foreground`, untinted.
 * Attention shows how many items it lists, on every page, split by severity, Pull requests how many review results the
 * operator has not opened, and Memory how many proposals wait on the operator, while proposals are on. Hovering an item
 * says what its page holds.
 *
 * `compact`, in the rail's strip under `lg`, shows the icons alone, each still named for a screen reader and on hover,
 * and each count as one number on its icon's corner: Attention's in its most severe item's color. It opens no pages
 * under a section, so the section stays active on them.
 */
export function Nav({ compact = false }: { compact?: boolean }) {
    const attention = useAttention()
    const counts = attention.data === undefined ? undefined : countBySeverity(attention.data)
    const waiting = useQuery(loopQuery).data?.memory?.proposals_waiting ?? 0
    const unseen = unseenOf(useQuery(reviewsQuery).data)
    const section = useSection()
    const matchRoute = useMatchRoute()
    // The pages open under the section shown, and the one of them shown, if any.
    const pages = compact ? [] : (ITEMS.find(({ to }) => to === section)?.pages ?? [])
    const page = pages.findIndex(({ to }) => matchRoute({ to, fuzzy: true }) !== false)
    const active = ITEMS.findIndex(({ to }) => to === section)
    // With no section active the highlight is hidden; it keeps a color so it fades rather than flashes.
    const tone = section ?? '/attention'
    return (
        <nav aria-label="Main" className="relative flex flex-col gap-0.5 p-2">
            <span
                aria-hidden
                data-testid="nav-highlight"
                className={cn(
                    'absolute top-2 right-2 overflow-hidden rounded-sm',
                    SECTION_TINT[tone],
                    'motion-safe:transition-[translate,left,height,opacity,background-color]',
                    'motion-safe:duration-300',
                    'motion-safe:ease-[cubic-bezier(0.2,0,0,1)]',
                    active === -1 && 'opacity-0',
                )}
                style={highlightAt(Math.max(active, 0), page)}
            >
                <span
                    className={cn(
                        'absolute inset-0 rounded-sm opacity-[var(--nav-block,0)]',
                        SECTION_FILL[tone],
                        'motion-safe:transition-colors motion-safe:duration-300',
                    )}
                />
                <span
                    className={cn(
                        'absolute inset-y-0 left-0 w-0.75 opacity-[var(--nav-hairline,1)]',
                        SECTION_FILL[tone],
                        'motion-safe:transition-colors motion-safe:duration-300',
                    )}
                />
            </span>
            {ITEMS.map(({ to, icon: Icon, hint }) => {
                // On a page under it, the section's item is not the page shown, that page's is, but it stays bright.
                const above = to === section && page !== -1
                return (
                    <Fragment key={to}>
                        <Link
                            to={to}
                            title={compact ? `${SECTION_LABEL[to]}: ${hint}` : hint}
                            activeOptions={{ exact: above }}
                            className={cn(
                                'group relative flex h-8 items-center gap-2.5 rounded-sm px-2.5 text-sm',
                                above ? 'text-foreground' : 'text-muted-foreground',
                                'transition-colors hover:bg-surface-raised hover:text-foreground',
                                SECTION_ACTIVE_INK[to],
                                'data-[status=active]:hover:bg-transparent',
                                compact && 'justify-center',
                            )}
                        >
                            <Icon
                                className={cn(
                                    'size-4 transition-transform group-hover:-rotate-6 motion-reduce:transition-none',
                                    'group-data-[status=active]:[filter:var(--nav-on-glow,none)]',
                                    SECTION_TEXT[to],
                                    'group-data-[status=active]:text-current',
                                )}
                            />
                            <span className={compact ? 'sr-only' : 'group-data-[status=active]:font-medium'}>
                                {SECTION_LABEL[to]}
                            </span>
                            {to === '/attention' && counts !== undefined && (
                                <AttentionCount counts={counts} compact={compact} />
                            )}
                            {to === '/pull-requests' && unseen.length > 0 && (
                                <ReviewCount unseen={unseen} compact={compact} />
                            )}
                            {to === '/memory' && waiting > 0 && <ProposalCount waiting={waiting} compact={compact} />}
                        </Link>
                        {to === section && pages.length > 0 && <SubPages section={to} pages={pages} />}
                    </Fragment>
                )
            })}
        </nav>
    )
}

// The nav's rows, in rem: a section's item is h-8, a page under one h-7, each gap-0.5 from the next.
const ITEM_HEIGHT = 2
const PAGE_HEIGHT = 1.75
const GAP = 0.125
// The nav's padding (p-2), where the highlight starts, and how far in a page's item starts (ml-6.5): its label, after
// its own px-2.5, then lines up with its section's, after px-2.5, a size-4 icon, and gap-2.5.
const INSET = 0.5
const PAGE_INDENT = 1.625

/**
 * Where the highlight sits: on the `item`th section's item, or on the `page`th page open under it, unless that is -1.
 */
function highlightAt(item: number, page: number): CSSProperties {
    const top = item * (ITEM_HEIGHT + GAP)
    if (page === -1) {
        return { translate: `0 ${top}rem`, left: `${INSET}rem`, height: `${ITEM_HEIGHT}rem` }
    }
    const below = top + ITEM_HEIGHT + GAP + page * (PAGE_HEIGHT + GAP)
    return { translate: `0 ${below}rem`, left: `${INSET + PAGE_INDENT}rem`, height: `${PAGE_HEIGHT}rem` }
}

/**
 * The pages under the section shown, under its item: smaller rows, muted, each label in line with the section's, on a
 * hairline in the section's color down the middle of its icon. The one shown, or the one a page shown is under, is
 * active, as a section's item is.
 */
function SubPages({ section, pages }: { section: Section; pages: SubPage[] }) {
    return (
        <div className="relative flex flex-col gap-0.5">
            <span
                aria-hidden
                className={cn('absolute inset-y-0 left-[calc(1.125rem-0.5px)] w-px', SECTION_FILL[section])}
            />
            {pages.map(({ to, label, hint }) => (
                <Link
                    key={to}
                    to={to}
                    title={hint}
                    activeOptions={{ exact: false }}
                    className={cn(
                        'relative ml-6.5 flex h-7 items-center rounded-sm px-2.5 text-sm text-muted-foreground',
                        'transition-colors hover:bg-surface-raised hover:text-foreground',
                        SECTION_ACTIVE_INK[section],
                        'data-[status=active]:font-medium data-[status=active]:hover:bg-transparent',
                    )}
                >
                    {label}
                </Link>
            ))}
        </div>
    )
}

/**
 * The attention list's count beside its nav item: what is broken in the failure color, what waits on the operator's
 * answer in theirs, and the rest muted, each shown only when there is one. Not the section's rose, which is too near
 * the failure color to tell apart at this size. Color alone does not say which number is which, so the numbers are
 * also said in words, on hover and to a screen reader (`1 broken, 1 waiting on you, 3 other`). `compact`, the total
 * alone on the icon's corner, in the first part's color: the most severe.
 */
function AttentionCount({ counts, compact }: { counts: Record<Severity, number>; compact: boolean }) {
    const parts = breakdown(counts)
    if (parts.length === 0) {
        return null
    }
    const said = breakdownText(parts)
    if (compact) {
        const total = parts.reduce((sum, { count }) => sum + count, 0)
        return (
            <span
                className={cn('absolute top-0 right-0.5 readout text-2xs', parts[0] && TONE[parts[0].kind])}
                title={said}
                data-testid="nav-attention-count"
            >
                <span aria-hidden>{total}</span>
                <span className="sr-only">{said}</span>
            </span>
        )
    }
    return (
        <span className="ml-auto flex gap-1.5 readout text-xs" title={said} data-testid="nav-attention-count">
            {parts.map(({ kind, count }) => (
                <span key={kind} aria-hidden className={TONE[kind]} data-testid={`nav-attention-${kind}`}>
                    {count}
                </span>
            ))}
            <span className="sr-only">{said}</span>
        </span>
    )
}

/**
 * How many reviews' results the operator has not opened beside Pull requests' nav item, the section the reviews are in
 * (src/lib/seen-reviews.ts), in the color of the worst finding among them, as a verdict wears it: a blocking one's in
 * the failure color, a major one's in the color of what waits on the operator, the rest muted. Said in words on hover
 * and to a screen reader (`2 new reviews to read`). `compact`, on the icon's corner.
 */
function ReviewCount({ unseen, compact }: { unseen: ReviewSummary[]; compact: boolean }) {
    const said = unseenText(unseen.length)
    const tone = verdictTone({ worst: worstOf(unseen) })
    return (
        <span
            className={cn(
                'readout',
                tone === '' ? 'text-muted-foreground' : tone,
                compact ? 'absolute top-0 right-0.5 text-2xs' : 'ml-auto text-xs',
            )}
            title={said}
            data-testid="nav-reviews-count"
        >
            <span aria-hidden>{unseen.length}</span>
            <span className="sr-only">{said}</span>
        </span>
    )
}

/**
 * How many proposals wait on the operator beside Memory's nav item, in the color of what waits on their answer, as
 * Attention's count shows it, and said in words on hover and to a screen reader (`2 proposals waiting on you`).
 * `compact`, on the icon's corner.
 */
function ProposalCount({ waiting, compact }: { waiting: number; compact: boolean }) {
    const said = `${counted(waiting, 'proposal')} waiting on you`
    return (
        <span
            className={cn(
                'readout text-status-blocked',
                compact ? 'absolute top-0 right-0.5 text-2xs' : 'ml-auto text-xs',
            )}
            title={said}
            data-testid="nav-memory-count"
        >
            <span aria-hidden>{waiting}</span>
            <span className="sr-only">{said}</span>
        </span>
    )
}
