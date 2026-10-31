import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * A command, key, or name inside a sentence, set as code (ui/DESIGN.md, "Rich text"): sized to its line and on a tint
 * of its own ink (`--code-size`, `--code-chip`), so it reads alike on a panel, a bubble, a tinted band, and a guide
 * page. Its ends are kept on each line it wraps to.
 */
export function Code({ children, className }: { children: ReactNode; className?: string }) {
    return (
        <code className={cn('rounded-sm bg-code-chip box-decoration-clone px-1 py-px font-mono text-code', className)}>
            {children}
        </code>
    )
}
