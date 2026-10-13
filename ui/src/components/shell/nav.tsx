import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
    Activity,
    CalendarClock,
    FolderTree,
    History,
    Inbox,
    MessagesSquare,
    SlidersHorizontal,
    type LucideIcon,
} from 'lucide-react'

import { attentionQuery } from '@/api/queries'
import { useSection } from '@/hooks/use-section'
import { type Section, SECTION_FILL, SECTION_TEXT, SECTION_TINT } from '@/lib/sections'
import { cn } from '@/lib/utils'

const ITEMS: { to: Section; label: string; icon: LucideIcon }[] = [
    { to: '/attention', label: 'Attention', icon: Inbox },
    { to: '/runs', label: 'Runs', icon: Activity },
    { to: '/worktrees', label: 'Worktrees', icon: FolderTree },
    { to: '/tickets', label: 'Tickets', icon: MessagesSquare },
    { to: '/chores', label: 'Chores', icon: CalendarClock },
    { to: '/ticks', label: 'Ticks', icon: History },
    { to: '/settings', label: 'Settings', icon: SlidersHorizontal },
]

/**
 * The side navigation. Each item's icon is in its section's color. The active item is marked by one highlight, a tint
 * and a hairline in that color, which slides to the item a navigation lands on and takes on its color as it goes; a
 * ticket's page keeps Tickets active, a chore's Chores, and a tick's Ticks. Attention shows how many items it lists, on
 * every page.
 */
export function Nav() {
    const attention = useQuery(attentionQuery)
    const listed = attention.data?.length
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
            {ITEMS.map(({ to, label, icon: Icon }) => (
                <Link
                    key={to}
                    to={to}
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
                    {label}
                    {to === '/attention' && listed !== undefined && listed > 0 && (
                        <span
                            className={cn('ml-auto readout text-xs', SECTION_TEXT[to])}
                            data-testid="nav-attention-count"
                        >
                            {listed}
                        </span>
                    )}
                </Link>
            ))}
        </nav>
    )
}
