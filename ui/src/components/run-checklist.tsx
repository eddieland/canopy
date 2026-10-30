import type { ChecklistAnswer } from '@/api/types'
import { Panel, PanelHeader } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { ListRow } from '@/components/rows'
import { Chip } from '@/components/status'
import { Clipped } from '@/components/tip'
import { ANSWER_MEANING, answersByRepo, answersLine } from '@/lib/checklist'
import { rowLineFrom } from '@/lib/rows'
import { cn } from '@/lib/utils'

/**
 * What a run answered of its repositories' checklists (DESIGN §42), as `canopy show run:ID` prints it: an item a row,
 * each list in its order, the answer's chip, then the item's id, and a held item's reason under it, the worker's words
 * laid out as text. A joint run's lists each sit under their repository's name; one list's repository is in the
 * header's readout, with how many gave each answer. Nothing for a run given no list.
 */
export function ChecklistPanel({ answers }: { answers: readonly ChecklistAnswer[] }) {
    if (answers.length === 0) {
        return null
    }
    const groups = answersByRepo(answers)
    const several = groups.length > 1
    return (
        <Panel data-testid="run-checklist">
            <PanelHeader label="Checklist">
                <span className="readout text-xs text-muted-foreground" data-testid="run-checklist-said">
                    {answersLine(answers)}
                </span>
            </PanelHeader>
            {groups.map((group, i) => (
                <section key={group.repo} aria-label={`${group.repo}'s checklist`} className={cn(i > 0 && 'border-t')}>
                    {several && <h3 className="px-3 pt-2 panel-label">{group.repo}</h3>}
                    <ul className="divide-y">
                        {group.answers.map((a) => (
                            <ListRow key={a.item} kind="checklist-answer" data-testid="checklist-answer">
                                <Chip
                                    className="justify-self-start"
                                    tone={a.answer === 'held' ? 'blocked' : 'plain'}
                                    word={a.answer}
                                    meaning={ANSWER_MEANING[a.answer]}
                                />
                                <Clipped text={a.item} className="block font-mono text-xs font-medium" />
                                {a.reason !== null && <RichText text={a.reason} className={rowLineFrom('item')} />}
                            </ListRow>
                        ))}
                    </ul>
                </section>
            ))}
        </Panel>
    )
}
