import { Outlet } from '@tanstack/react-router'
import { ViewTransition } from 'react'

import { useLiveUpdates } from '@/hooks/use-live-updates'
import { cn } from '@/lib/utils'

import { LiveReadouts } from './live-readouts'
import { Nav } from './nav'
import { ThemeToggle } from './theme-toggle'

/**
 * The frame every page renders in: header, side navigation, and the routed page.
 *
 * Navigations run inside React transitions (TanStack Router starts them), so the old page stays until the new one
 * is ready, and the <ViewTransition> around the outlet cross-fades between them.
 */
export function AppShell() {
    const stream = useLiveUpdates()
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
            <aside className="sticky top-12 h-[calc(100dvh-3rem)] border-r bg-surface/60">
                <Nav />
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

/** The logo: a ring and a dot, in the accent color. */
function Mark() {
    return (
        <svg viewBox="0 0 16 16" className="size-4 text-accent" aria-hidden>
            <circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <circle cx="8" cy="8" r="2" fill="currentColor" />
        </svg>
    )
}
