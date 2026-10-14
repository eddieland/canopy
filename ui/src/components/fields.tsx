import type { ComponentProps, ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * A detail page's field list: a label column of one width on every page, and the values beside it. Each row sits on
 * its first line's baseline, so a label stays level with the first line of a value that wraps.
 */
export function Fields({ className, ...props }: ComponentProps<'dl'>) {
    return (
        <dl
            className={cn(
                'grid grid-cols-[8rem_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1.5 p-3 text-sm',
                className,
            )}
            {...props}
        />
    )
}

/** One field in `Fields`: its label, and its value in prose, or in monospace for data (`mono`). */
export function Field({
    label,
    mono = false,
    className,
    children,
    ...props
}: ComponentProps<'dd'> & { label: ReactNode; mono?: boolean }) {
    return (
        <>
            <dt className="panel-label">{label}</dt>
            <dd
                className={cn('min-w-0 break-words', mono ? 'font-mono text-xs break-all' : 'text-sm', className)}
                {...props}
            >
                {children}
            </dd>
        </>
    )
}
