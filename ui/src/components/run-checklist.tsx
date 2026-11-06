import type { ChecklistAnswer, ChecklistStretch } from '@/api/types'
import { Empty, Panel, PanelHeader } from '@/components/panel'
import { DiffPanels } from '@/components/review-diff'
import { RichText } from '@/components/rich-text'
import { ListRow, RowList } from '@/components/rows'
import { Chip } from '@/components/status'
import { Clipped } from '@/components/tip'
import { ANSWER_MEANING, answersByRepo, answersLine, stretchesLeftOutText, stretchRange } from '@/lib/checklist'
import { goneText } from '@/lib/retention'
import type { Placed } from '@/lib/reviews'
import { rowLineFrom } from '@/lib/rows'
import { cn } from '@/lib/utils'

// A run that pushed nothing after its list: a stable default.
const NO_STRETCHES: readonly ChecklistStretch[] = []
// Nothing is placed on a stretch's diff: it is read for itself, beside the answers above it.
const NOTHING_PLACED: Placed<never> = { lines: new Map(), files: new Map(), elsewhere: [] }
const NO_STRETCH = 'no diff kept for this stretch: canopy could not read it as the run ended, or its file is not one'
const NO_CHANGE = 'no change: the run pushed the commit it was shown the list at'
const STRETCH =
    'What the run changed from the commit it was shown the list at to the push after it: the fixes its answers ' +
    'speak of, with whatever else it did in that stretch.'

/**
 * What a run answered of its repositories' checklists (DESIGN §42), as `canopy show run:ID` prints it: an item a row,
 * each list in its order, the answer's chip, then the item's id, and a held item's reason under it, the worker's words
 * laid out as text. A joint run's lists each sit under their repository's name; one list's repository is in the
 * header's readout, with how many gave each answer. Under the panel, each stretch the run pushed after being shown a
 * list (`StretchDiff`), so the answers and the fix are read together, and how many more the page was not sent, which
 * `canopy show <shownBy>` names. Nothing for a run given no list.
 */
export function ChecklistPanel({
    answers,
    stretches = NO_STRETCHES,
    leftOut = 0,
    shownBy = '',
}: {
    answers: readonly ChecklistAnswer[]
    stretches?: readonly ChecklistStretch[]
    leftOut?: number
    shownBy?: string
}) {
    if (answers.length === 0 && stretches.length === 0) {
        return null
    }
    return (
        <>
            {answers.length > 0 && <Answers answers={answers} />}
            {stretches.map((stretch, i) => (
                <StretchDiff key={`${i}:${stretch.repo}:${stretch.shown_sha}`} stretch={stretch} />
            ))}
            {leftOut > 0 && (
                <p className="font-mono text-xs text-muted-foreground" data-testid="checklist-stretches-left-out">
                    {stretchesLeftOutText(leftOut, shownBy)}
                </p>
            )}
        </>
    )
}

function Answers({ answers }: { answers: readonly ChecklistAnswer[] }) {
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
                    <RowList kind="checklist-answer" className="divide-y">
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
                    </RowList>
                </section>
            ))}
        </Panel>
    )
}

/**
 * One stretch a run pushed after being shown its repository's list: a panel naming the repository and the two commits,
 * then the diff between them in the panels a review's diff has (`DiffPanels`), the branch's own text. A diff canopy did
 * not keep, or retention removed, says so in the panel rather than leaving the stretch out.
 */
function StretchDiff({ stretch }: { stretch: ChecklistStretch }) {
    const { diff } = stretch
    const range = stretchRange(stretch)
    return (
        <section aria-label={`Pushed after the list: ${range}`} className="flex flex-col gap-6">
            <Panel data-testid="checklist-stretch">
                <PanelHeader label="Pushed after the list">
                    <span className="readout text-xs text-muted-foreground" data-testid="checklist-stretch-range">
                        {range}
                    </span>
                </PanelHeader>
                {diff === null ? (
                    <Empty>{goneText(stretch.diff_removed_after_days, NO_STRETCH)}</Empty>
                ) : diff.files.length === 0 ? (
                    <Empty>{NO_CHANGE}</Empty>
                ) : (
                    <p className="px-3 py-2.5 text-sm text-muted-foreground">{STRETCH}</p>
                )}
            </Panel>
            {diff !== null && diff.files.length > 0 && (
                <DiffPanels diff={diff} placed={NOTHING_PLACED} cards={['note', 'notes']} renderCard={() => null} />
            )}
        </section>
    )
}
