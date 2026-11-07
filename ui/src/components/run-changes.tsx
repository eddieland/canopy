import { useState } from 'react'

import type { RunChange } from '@/api/types'
import { Empty, Panel, PanelHeader } from '@/components/panel'
import { DiffPanels } from '@/components/review-diff'
import { Chip } from '@/components/status'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { Placed } from '@/lib/reviews'
import { missingText, NOT_ON_ORIGIN, NOTHING_RECORDED, noChangeText, rangeText, viewText } from '@/lib/run-changes'
import type { ChangeView } from '@/lib/run-changes'

// A run that recorded nothing: a stable default.
const NO_CHANGES: readonly RunChange[] = []
// Nothing is placed on a run's diff: it is read for itself.
const NOTHING_PLACED: Placed<never> = { lines: new Map(), files: new Map(), elsewhere: [] }

/**
 * What a worker's or a task's run changed (DESIGN §45), a section per repository it recorded, by repository: a Diff
 * panel naming the repository and the commits, then the diff in the panels a review's diff has (`DiffPanels`). Each
 * opens on the run's own change, and a toggle in its header turns it to the branch against its base. A slot the run
 * left unpushed says its diff is of work not on origin; a diff canopy did not keep says why, or that retention removed
 * it, rather than showing nothing. A run that recorded nothing says so when `records`, as an ended run of a kind that
 * records would have; otherwise, and while it runs, there is no panel.
 */
export function RunChangesPanel({
    changes = NO_CHANGES,
    records,
}: {
    changes?: readonly RunChange[]
    records: boolean
}) {
    if (changes.length === 0) {
        return records ? (
            <Panel data-testid="run-change">
                <PanelHeader label="Diff" />
                <Empty>{NOTHING_RECORDED}</Empty>
            </Panel>
        ) : null
    }
    return (
        <>
            {changes.map((change) => (
                <ChangeDiff key={change.range.repo} change={change} />
            ))}
        </>
    )
}

/** One repository's change: its panel, with the toggle between the two diffs, then the diff shown. */
function ChangeDiff({ change }: { change: RunChange }) {
    const [view, setView] = useState<ChangeView>('run')
    const range = rangeText(change.range)
    const diff = view === 'run' ? change.diff : change.branch_diff
    const unpushed = change.range.unpushed_sha !== null
    return (
        <section aria-label={`Diff: ${range}`} className="flex flex-col gap-6">
            <Panel data-testid="run-change">
                <PanelHeader label="Diff">
                    <span className="flex min-w-0 flex-1 items-center gap-3">
                        <span className="readout truncate text-xs text-muted-foreground" data-testid="run-change-range">
                            {range}
                        </span>
                        {unpushed && <Chip tone="blocked">not on origin</Chip>}
                    </span>
                    {(change.diff !== null || change.branch_diff !== null) && (
                        <ToggleGroup
                            type="single"
                            value={view}
                            aria-label="Diff of"
                            onValueChange={(value) => {
                                // Pressing the one shown turns it off, which reads as no value: keep it.
                                if (value === 'run' || value === 'branch') {
                                    setView(value)
                                }
                            }}
                        >
                            <ToggleGroupItem value="run">This run</ToggleGroupItem>
                            <ToggleGroupItem value="branch">Branch vs base</ToggleGroupItem>
                        </ToggleGroup>
                    )}
                </PanelHeader>
                {unpushed && (
                    <p className="border-b px-3 py-2.5 text-sm text-status-blocked" data-testid="run-change-unpushed">
                        {NOT_ON_ORIGIN}
                    </p>
                )}
                {diff === null ? (
                    <Empty>{missingText(change, view)}</Empty>
                ) : diff.files.length === 0 ? (
                    <Empty>{noChangeText(view)}</Empty>
                ) : (
                    <p className="px-3 py-2.5 text-sm text-muted-foreground">{viewText(change, view)}</p>
                )}
            </Panel>
            {diff !== null && diff.files.length > 0 && (
                <DiffPanels
                    key={view}
                    diff={diff}
                    placed={NOTHING_PLACED}
                    cards={['note', 'notes']}
                    renderCard={() => null}
                />
            )}
        </section>
    )
}
