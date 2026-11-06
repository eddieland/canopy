import type { EpicPlanRun, EpicSummary } from '@/api/types'
import { Age } from '@/components/age'
import { Cost } from '@/components/cost'
import { EpicLink } from '@/components/epic-link'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { ListRow, RowLine } from '@/components/rows'
import { RunDot, Word } from '@/components/status'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped } from '@/components/tip'
import { EPIC_LOOK, entriesFiled, epicTitle } from '@/lib/epics'
import { epicRunRef } from '@/lib/refs'
import { rowLineFrom } from '@/lib/rows'
import { RUN_TEXT } from '@/lib/run-state'
import { cn } from '@/lib/utils'

/**
 * An epic in the epics list: where it stands, in its run state's dot and color (`EPIC_LOOK`), with the CLI's word and
 * what it means on hover; `epic:N`, opening its page; its repositories; its goal's first line, the operator's words,
 * as text; how many of its breakdown's entries are filed (`entriesFiled`); and when it was submitted. Under its goal, a
 * stopped epic says when the operator stopped it, its standing's word `planning` too while its plan run finishes.
 */
export function EpicRow({ epic }: { epic: EpicSummary }) {
    const look = EPIC_LOOK[epic.standing]
    const filed = entriesFiled(epic)
    const repos = epic.repos.join(', ')
    return (
        <ListRow kind="epic" data-testid={`epic-${String(epic.id)}`}>
            <span className={cn('flex items-center gap-1.5 font-mono text-xs whitespace-nowrap', RUN_TEXT[look.state])}>
                <RunDot state={look.state} />
                <Word word={epic.standing} text={look.word} meaning={look.meaning} />
            </span>
            <EpicLink id={epic.id} />
            <Clipped text={repos} mono className="text-xs text-muted-foreground" />
            <TicketTitle title={epicTitle(epic.text)} />
            <span className="readout text-right text-xs text-muted-foreground">{filed}</span>
            <Age at={epic.submitted_at} variant="ago" className="text-right" />
            {epic.stopped_at !== null && (
                <RowLine from="title" className="text-xs text-muted-foreground" data-testid="epic-stopped">
                    stopped <Age at={epic.stopped_at} variant="ago" />
                </RowLine>
            )}
        </ListRow>
    )
}

/**
 * One plan run of an epic on its page, in a run's columns there (`own-run`), as a task's runs are listed: its state,
 * its reference (`epic:2#3`), cost, and when; under them, the question it asked, or else what it said, the planner's
 * words as text. It has no page of its own, so its reference is not a link.
 */
export function EpicRunRow({ epic, run }: { epic: number; run: EpicPlanRun }) {
    const said = run.question ?? run.summary ?? null
    return (
        <ListRow kind="own-run" data-testid={`epic-run-${String(run.id)}`}>
            <span className={cn('flex items-center gap-1.5 font-mono text-xs', RUN_TEXT[run.state])}>
                <RunDot state={run.state} />
                <Word word={run.status} />
            </span>
            <span className="readout text-xs">{epicRunRef(epic, run.id)}</span>
            <span className="text-right text-xs text-muted-foreground">
                <Cost usd={run.cost_usd ?? null} />
            </span>
            <Age variant="span" started={run.started_at} ended={run.ended_at ?? null} className="text-right" />
            {said !== null && said !== '' && (
                <RichText text={said} lines={SUMMARY_LINES} className={rowLineFrom('facts')} />
            )}
        </ListRow>
    )
}
