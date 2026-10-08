import { useQuery } from '@tanstack/react-query'
import { Outlet } from '@tanstack/react-router'
import { ViewTransition } from 'react'

import { sessionQuery } from '@/api/queries'
import { SignIn } from '@/components/sign-in'
import { useLiveUpdates } from '@/hooks/use-live-updates'
import { cn } from '@/lib/utils'
import { useTheme } from '@/theme/use-theme'

import { LiveReadouts } from './live-readouts'
import { Mark } from './mark'
import { Nav } from './nav'
import { ThemeToggle } from './theme-toggle'

/**
 * The frame every page renders in: header, side navigation, and the routed page. Signed out, the sign-in page instead,
 * whatever the route: every API route but the session's needs a session (DESIGN §22).
 *
 * Navigations run inside React transitions (TanStack Router starts them), so the old page stays until the new one
 * is ready, and the <ViewTransition> around the outlet cross-fades between them.
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
                <div className="flex items-center gap-2.5">
                    <Mark />
                    <span className="font-mono text-sm font-medium tracking-tight">canopy</span>
                </div>
                <div className="flex items-center gap-4">
                    <LiveReadouts stream={stream} />
                    <span aria-hidden className="h-5 w-px bg-border" />
                    <ThemeToggle />
                </div>
            </header>
            {/* The rail spans the whole row, so its border and fill reach the page's foot; only the nav sticks. */}
            <aside className="border-r bg-surface/60">
                <div className="sticky top-12">
                    <Nav />
                </div>
            </aside>
            <main className="min-w-0 p-6">
                <ViewTransition>
                    <div className="mx-auto flex max-w-6xl flex-col gap-6">
                        <Outlet />
                    </div>
                </ViewTransition>
            </main>
        </div>
    )
}
