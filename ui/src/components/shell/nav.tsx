import { useQuery } from '@tanstack/react-query'
import { Link, useMatchRoute } from '@tanstack/react-router'
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
import { cn } from '@/lib/utils'

type To = '/attention' | '/runs' | '/worktrees' | '/tickets' | '/chores' | '/ticks' | '/settings'

const ITEMS: { to: To; label: string; icon: LucideIcon }[] = [
    { to: '/attention', label: 'Attention', icon: Inbox },
    { to: '/runs', label: 'Runs', icon: Activity },
    { to: '/worktrees', label: 'Worktrees', icon: FolderTree },
    { to: '/tickets', label: 'Tickets', icon: MessagesSquare },
    { to: '/chores', label: 'Chores', icon: CalendarClock },
    { to: '/ticks', label: 'Ticks', icon: History },
    { to: '/settings', label: 'Settings', icon: SlidersHorizontal },
]

/**
 * The side navigation. The active item is marked by one highlight with the accent hairline, which slides to the item
 * a navigation lands on; a ticket's page keeps Tickets active, a chore's Chores, and a tick's Ticks. Attention shows
 * how many items it lists, on every page.
 */
export function Nav() {
    const attention = useQuery(attentionQuery)
    const listed = attention.data?.length
    const matchRoute = useMatchRoute()
    const active = ITEMS.findIndex(({ to }) => matchRoute({ to, fuzzy: true }) !== false)
    return (
        <nav aria-label="Main" className="relative flex flex-col gap-0.5 p-2">
            <span
                aria-hidden
                data-testid="nav-highlight"
                className={cn(
                    'absolute inset-x-2 top-2 h-8 rounded-sm bg-accent/16',
                    'motion-safe:transition-[translate,opacity] motion-safe:duration-300',
                    'motion-safe:ease-[cubic-bezier(0.2,0,0,1)]',
                    active === -1 && 'opacity-0',
                )}
                // Items are h-8 apart by gap-0.5: 2.125rem from one to the next.
                style={{ translate: `0 ${Math.max(active, 0) * 2.125}rem` }}
            >
                <span className="absolute inset-y-1.5 left-0 w-px bg-accent" />
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
                            'size-4 transition-[rotate,color] group-hover:-rotate-6 motion-reduce:transition-none',
                            'group-data-[status=active]:text-accent',
                        )}
                    />
                    {label}
                    {to === '/attention' && listed !== undefined && listed > 0 && (
                        <span className="ml-auto readout text-xs text-accent" data-testid="nav-attention-count">
                            {listed}
                        </span>
                    )}
                </Link>
            ))}
        </nav>
    )
}
