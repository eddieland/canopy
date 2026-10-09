import { Link } from '@tanstack/react-router'

import { cn } from '@/lib/utils'

/** A chore's name, as `chore:NAME`, that opens its page. */
export function ChoreLink({ name, className }: { name: string; className?: string }) {
    return (
        <Link
            to="/chores/$name"
            params={{ name }}
            className={cn('font-mono text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            chore:{name}
        </Link>
    )
}
