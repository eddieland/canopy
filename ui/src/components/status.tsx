import type { LeaseState, SessionState } from '@/api/types'
import { cn } from '@/lib/utils'

// Full class names, written out, so Tailwind finds them. One entry per state; the types make a missing one an error.
const SESSION_DOT: Record<SessionState, string> = {
    running: 'bg-status-running',
    blocked: 'bg-status-blocked',
    idle: 'bg-status-idle',
    done: 'bg-status-done',
    failed: 'bg-status-failed',
}

const LEASE_DOT: Record<LeaseState, string> = {
    held: 'bg-lease-held',
    expiring: 'bg-lease-expiring',
    released: 'bg-lease-released',
}

const PULSE: ReadonlySet<string> = new Set<SessionState | LeaseState>(['running', 'expiring'])

interface DotProps {
    className?: string
}

/** A small round marker in a session state's color. `running` pulses. */
export function SessionDot({ state, className }: DotProps & { state: SessionState }) {
    return <Dot tone={SESSION_DOT[state]} pulse={PULSE.has(state)} className={className} />
}

/** A small round marker in a lease state's color. `expiring` pulses. */
export function LeaseDot({ state, className }: DotProps & { state: LeaseState }) {
    return <Dot tone={LEASE_DOT[state]} pulse={PULSE.has(state)} className={className} />
}

function Dot({ tone, pulse, className }: { tone: string; pulse: boolean; className?: string | undefined }) {
    return (
        <span aria-hidden className={cn('relative inline-flex size-2 shrink-0', className)}>
            {pulse && (
                <span
                    className={cn('absolute inset-0 animate-ping rounded-full opacity-40 motion-reduce:hidden', tone)}
                />
            )}
            <span className={cn('relative inline-flex size-2 rounded-full', tone)} />
        </span>
    )
}
