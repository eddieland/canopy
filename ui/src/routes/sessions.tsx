import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { SESSION_STATES, type SessionState } from '@/api/types'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { SessionDot } from '@/components/status'
import { cn } from '@/lib/utils'

interface SessionsSearch {
    state?: SessionState | undefined
}

export const Route = createFileRoute('/sessions')({
    // Typed search params: `?state=blocked` filters; anything else is dropped, never trusted. Return every key, even
    // when undefined: the router merges this over the raw search, so an omitted key would keep the raw value.
    validateSearch: (search: Record<string, unknown>): SessionsSearch => ({
        state: SESSION_STATES.find((s) => s === search['state']),
    }),
    component: SessionsPage,
})

function SessionsPage() {
    const { state } = Route.useSearch()
    return (
        <>
            <PageHeader label="Runs" title="Sessions">
                Agent runs canopy started: what each is doing, its worktree, and what it has cost.
            </PageHeader>
            <Panel>
                <PanelHeader label="By state">
                    <nav aria-label="Filter by state" className="flex items-center gap-1">
                        <FilterLink search={{ state: undefined }}>all</FilterLink>
                        {SESSION_STATES.map((s) => (
                            <FilterLink key={s} search={{ state: s }}>
                                <SessionDot state={s} />
                                {s}
                            </FilterLink>
                        ))}
                    </nav>
                </PanelHeader>
                <Placeholder>sessions table: a later task{state ? ` · filtered to ${state}` : ''}</Placeholder>
            </Panel>
        </>
    )
}

/** A filter chip, selected when it matches the validated search: an unknown `?state=` selects `all`. */
function FilterLink({ search, children }: { search: SessionsSearch; children: ReactNode }) {
    const { state } = Route.useSearch()
    return (
        <Link
            to="/sessions"
            search={search}
            data-selected={search.state === state}
            className={cn(
                'flex h-6 items-center gap-1.5 rounded-sm px-2 font-mono text-xs text-muted-foreground',
                'hover:bg-surface-raised hover:text-foreground',
                'data-[selected=true]:bg-surface-raised data-[selected=true]:text-foreground',
            )}
        >
            {children}
        </Link>
    )
}
