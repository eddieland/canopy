import type { EpicEntry, EpicId, EpicOutline } from '@/api/types'
import { OutlineId } from '@/components/epic-ids'
import { Empty, Panel, PanelHeader } from '@/components/panel'
import { InlineCode } from '@/components/rich-text'
import { useLit } from '@/hooks/use-outline-lights'
import { citedBy } from '@/lib/epics'
import { cn } from '@/lib/utils'

/**
 * An epic plan's requirements and contracts (DESIGN §43), each id with what the plan says of it: the key to the
 * breakdown's cells. Each id's tip says who in the breakdown cites it, so a requirement no entry covers shows; pointing
 * at one lights it and the entries that cite it, on the board above. The words are the planner's, as text, with their
 * `code` spans set as code. With no plan to read, it says why in a line.
 */
export function OutlinePanel({ outline, className }: { outline: EpicOutline | null; className?: string }) {
    return (
        <Panel className={className} data-testid="epic-outline">
            <PanelHeader label="Requirements and contracts" />
            {outline === null ? (
                <Empty>no requirements yet: its plan names them</Empty>
            ) : outline.problem === null ? (
                <>
                    <Ids label="Requirements" ids={outline.requirements} entries={outline.entries} />
                    <Ids label="Contracts" ids={outline.contracts} entries={outline.entries} />
                </>
            ) : (
                <Empty>none read: its plan does not read, as its breakdown says</Empty>
            )}
        </Panel>
    )
}

/** One kind of id, under its heading: each a row of its id and its text, lit while its id is pointed at. */
function Ids({ label, ids, entries }: { label: string; ids: readonly EpicId[]; entries: readonly EpicEntry[] }) {
    return (
        <section className="flex flex-col gap-1 border-b py-2.5 last:border-b-0">
            <h3 className="px-3 panel-label">{label}</h3>
            {ids.length === 0 ? (
                <p className="px-3 text-sm text-muted-foreground">none</p>
            ) : (
                <ul className="flex flex-col">
                    {ids.map((id) => (
                        <IdLine key={id.id} id={id} entries={entries} />
                    ))}
                </ul>
            )}
        </section>
    )
}

function IdLine({ id, entries }: { id: EpicId; entries: readonly EpicEntry[] }) {
    const on = useLit() === id.id
    return (
        <li
            data-lit={on ? '' : undefined}
            className={cn(
                'flex items-baseline gap-3 px-3 py-1 text-sm',
                'motion-safe:transition-colors motion-safe:duration-150 motion-safe:ease-out',
                on && 'bg-accent/10',
            )}
        >
            <OutlineId id={id.id} fact={citedBy(entries, id.id)} className="-ml-1 shrink-0" />
            <span className="min-w-0 wrap-break-word">
                <InlineCode text={id.text} links={false} />
            </span>
        </li>
    )
}
