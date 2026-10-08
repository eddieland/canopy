import { createFileRoute } from '@tanstack/react-router'

import { LEASE_STATES } from '@/api/types'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { LeaseDot } from '@/components/status'

export const Route = createFileRoute('/worktrees')({
    component: WorktreesPage,
})

function WorktreesPage() {
    return (
        <>
            <PageHeader label="Pool" title="Worktrees">
                Leases on the worktree pool: which run holds each, and when it expires.
            </PageHeader>
            <Panel>
                <PanelHeader label="Lease states">
                    <div className="flex items-center gap-3">
                        {LEASE_STATES.map((s) => (
                            <span key={s} className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                                <LeaseDot state={s} />
                                {s}
                            </span>
                        ))}
                    </div>
                </PanelHeader>
                <Placeholder>worktrees table: a later task</Placeholder>
            </Panel>
        </>
    )
}
