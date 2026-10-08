import { Link } from '@tanstack/react-router'
import { Activity, FolderGit2, SlidersHorizontal, type LucideIcon } from 'lucide-react'

import { cn } from '@/lib/utils'

const ITEMS: { to: '/sessions' | '/worktrees' | '/settings'; label: string; icon: LucideIcon }[] = [
    { to: '/sessions', label: 'Sessions', icon: Activity },
    { to: '/worktrees', label: 'Worktrees', icon: FolderGit2 },
    { to: '/settings', label: 'Settings', icon: SlidersHorizontal },
]

/** The side navigation. The active item gets the accent hairline. */
export function Nav() {
    return (
        <nav aria-label="Main" className="flex flex-col gap-0.5 p-2">
            {ITEMS.map(({ to, label, icon: Icon }) => (
                <Link
                    key={to}
                    to={to}
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
