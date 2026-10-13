import { useQuery } from '@tanstack/react-query'
import { Outlet } from '@tanstack/react-router'
import { ViewTransition } from 'react'

import { sessionQuery, tickQuery } from '@/api/queries'
import { SignIn } from '@/components/sign-in'
import type { StreamStatus } from '@/hooks/use-event-stream'
import { useLiveUpdates } from '@/hooks/use-live-updates'
import { cn } from '@/lib/utils'
import { useTheme } from '@/theme/use-theme'

import { LiveReadouts } from './live-readouts'
import { LoopPause } from './loop-pause'
import { Mark } from './mark'
import { Nav } from './nav'
import { RailFooter, RailSpend, RailWorking } from './rail'
import { SearchBox } from './search-box'
import { ThemeToggle } from './theme-toggle'
import { Ticker } from './ticker'

/**
 * The frame every page renders in: header (with its ticker), side rail (search, navigation, the runs working now, the
 * spend, and a footer), and the routed page. Signed out, the sign-in page instead, whatever the route: every API route
 * but the session's needs a session (DESIGN §22).
 *
 * Navigations run inside React transitions (TanStack Router starts them), so the old page stays until the new one
 * is ready, and the <ViewTransition> around the outlet cross-fades between them. The new page's blocks rise in one
 * after another (`stagger`).
 */
export function AppShell() {
    // Follows the system theme and other tabs on every page, the sign-in page included.
    useTheme()
    const session = useQuery(sessionQuery)
    const signedIn = session.data?.signed_in === true
    const stream = useLiveUpdates(signedIn)
    if (session.data === undefined) return <div className="min-h-dvh" />
    if (!signedIn) return <SignIn />
    return (
        <div className="grid min-h-dvh grid-cols-[13rem_minmax(0,1fr)] grid-rows-[3rem_minmax(0,1fr)]">
            <header
                data-testid="app-header"
                className={cn(
                    'sticky top-0 z-10 col-span-2 flex items-center justify-between gap-4',
                    'border-b bg-surface/85 px-4 backdrop-blur',
                )}
            >
                {/* The aurora: a hairline through the sections' colors along the header's foot, over its border. */}
                <span
                    aria-hidden
                    className={cn(
                        'pointer-events-none absolute inset-x-0 -bottom-px h-0.5 opacity-90',
                        'bg-linear-to-r from-section-attention via-section-runs to-section-worktrees',
                    )}
                />
                <div className="flex items-center gap-2.5">
                    <LiveMark stream={stream} />
                    <span className="font-mono text-sm font-medium tracking-tight">canopy</span>
                </div>
                <Ticker />
                {/* Three groups, the action, the readouts, and the theme, a rule between each. */}
                <div className="flex items-center gap-2">
                    <LoopPause />
                    <Rule />
                    <LiveReadouts stream={stream} />
                    <Rule />
                    <ThemeToggle />
                </div>
            </header>
            {/* The rail spans the whole row, so its border and fill reach the page's foot; only the nav and what is
                under it stick, and the footer sits at the rail's foot. */}
            <aside className="flex flex-col border-r bg-surface/60">
                <div className="sticky top-12">
                    <SearchBox />
                    <Nav />
                    <RailWorking />
                    <RailSpend />
                </div>
                <div className="mt-auto pt-3">
                    <RailFooter />
                </div>
            </aside>
            <main className="min-w-0 p-6">
                <ViewTransition>
                    <div className="stagger mx-auto flex max-w-[112rem] flex-col gap-6">
                        <Outlet />
                    </div>
                </ViewTransition>
            </main>
        </div>
    )
}

/** The header's logo, alive with the stream and the latest tick. */
function LiveMark({ stream }: { stream: StreamStatus }) {
    const tick = useQuery(tickQuery).data?.tick
    return <Mark live={stream === 'open'} ticking={tick?.status === 'running'} beat={tick?.id} />
}

/** A hairline between the header's groups. */
function Rule() {
    return <span aria-hidden className="h-5 w-px bg-border" />
}
