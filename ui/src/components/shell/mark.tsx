import { cn } from '@/lib/utils'

/**
 * The logo: a ring and a dot, in the accent color. In the header it is alive: the dot breathes while the stream is
 * live, an arc sweeps the ring while a tick runs, and a ripple leaves it each time a new tick appears (`beat`).
 */
export function Mark({ live = false, ticking = false, beat }: { live?: boolean; ticking?: boolean; beat?: number }) {
    return (
        <span className="relative inline-flex size-4 text-accent" data-testid="mark">
            <svg viewBox="0 0 16 16" className="size-4" aria-hidden>
                <circle
                    cx="8"
                    cy="8"
                    r="6.25"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    className={cn('transition-opacity', ticking && 'opacity-35')}
                />
                {ticking && (
                    <circle
                        cx="8"
                        cy="8"
                        r="6.25"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeDasharray="12 40"
                        className="animate-sweep"
                    />
                )}
                <circle cx="8" cy="8" r="2" fill="currentColor" className={cn(live && 'animate-breathe')} />
            </svg>
            {beat !== undefined && (
                <span
                    key={beat}
                    aria-hidden
                    className="pointer-events-none absolute inset-0 animate-ripple rounded-full border border-accent"
                />
            )}
        </span>
    )
}
