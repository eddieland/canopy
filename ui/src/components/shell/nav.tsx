import { Link } from '@tanstack/react-router'
import { Activity, FolderTree, Inbox, MessagesSquare, SlidersHorizontal, type LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

type To = '/attention' | '/runs' | '/worktrees' | '/tickets' | '/settings'

const ITEMS: { to: To; label: string; icon: LucideIcon }[] = [
    { to: '/attention', label: 'Attention', icon: Inbox },
    { to: '/runs', label: 'Runs', icon: Activity },
    { to: '/worktrees', label: 'Worktrees', icon: FolderTree },
    { to: '/tickets', label: 'Tickets', icon: MessagesSquare },
    { to: '/settings', label: 'Settings', icon: SlidersHorizontal },
]

/** The side navigation. The active item gets the accent hairline; a ticket's page keeps Tickets active. */
export function Nav() {
    return (
        <nav aria-label="Main" className="flex flex-col gap-0.5 p-2">
            {ITEMS.map(({ to, label, icon: Icon }) => (
                <Link
                    key={to}
                    to={to}
                    activeOptions={{ exact: false }}
                    className={cn(
                        'group relative flex h-8 items-center gap-2.5 rounded-sm px-2.5 text-sm text-muted-foreground',
                        'transition-colors hover:bg-surface-raised hover:text-foreground',
                        'data-[status=active]:bg-surface-raised data-[status=active]:text-foreground',
                    )}
                >
                    <span
                        aria-hidden
                        className={cn(
                            'absolute inset-y-1.5 left-0 w-px bg-accent opacity-0 transition-opacity',
                            'group-data-[status=active]:opacity-100',
                        )}
                    />
                    <Icon className="size-4" />
                    {label}
                </Link>
            ))}
        </nav>
    )
}
