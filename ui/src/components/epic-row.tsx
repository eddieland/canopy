import type { EpicSummary } from '@/api/types'
import { Age } from '@/components/age'
import { ListRow } from '@/components/rows'
import { RunDot, Word } from '@/components/status'
import { TicketTitle } from '@/components/ticket-title'
import { Clipped } from '@/components/tip'
import { EPIC_LOOK, entriesFiled, epicTitle } from '@/lib/epics'
import { epicRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { cn } from '@/lib/utils'

/**
 * An epic in the epics list: where it stands, in its run state's dot and color (`EPIC_LOOK`), with the CLI's word and
 * what it means on hover; `epic:N`; its repositories; its goal's first line, the operator's words, as text; how many
 * of its breakdown's entries are filed (`entriesFiled`); and when it was submitted.
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
            <span className="readout text-xs">{epicRef(epic.id)}</span>
            <Clipped text={repos} mono className="text-xs text-muted-foreground" />
            <TicketTitle title={epicTitle(epic.text)} />
            <span className="readout text-right text-xs text-muted-foreground">{filed}</span>
            <Age at={epic.submitted_at} variant="ago" className="text-right" />
        </ListRow>
    )
}
