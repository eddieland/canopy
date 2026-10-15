import { Link } from '@tanstack/react-router'

import { choreRef, choreRunRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/** A chore's name, as `chore:NAME`, that opens its page. */
export function ChoreLink({ name, className }: { name: string; className?: string }) {
    return (
        <Link
            to="/chores/$name"
            params={{ name }}
            className={cn('font-mono text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            {choreRef(name)}
        </Link>
    )
}

/** One run of a chore, as `chore:NAME#N`, that opens its page: what it checked, its findings, and its session. */
export function ChoreRunLink({ name, id, className }: { name: string; id: number; className?: string }) {
    return (
        <Link
            to="/chores/$name/runs/$id"
            params={{ name, id: String(id) }}
            className={cn('readout text-xs text-accent underline-offset-4 hover:underline', className)}
        >
            {choreRunRef(name, id)}
        </Link>
    )
}
