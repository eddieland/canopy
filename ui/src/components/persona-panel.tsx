import type { RunPersona } from '@/api/types'
import { CopyButton } from '@/components/copy-button'
import { FoldPanel } from '@/components/fold-panel'
import { Empty, PanelScroll } from '@/components/panel'
import { DIGEST_WIDTH } from '@/components/persona-field'
import { RichText } from '@/components/rich-text'

/**
 * The persona a run wrote in (DESIGN §31), and its instructions: its name and the start of its digest as the readout,
 * as `PersonaField` shows them, and `Show instructions` opening its text. The journal keeps the digest, not the text,
 * so the text is its file's now: when that differs from what the run read, it says so first, and a file that has gone
 * says why in its place. Laid out as the Markdown it is, its wrapped lines joined, and rendered as React text.
 */
export function PersonaPanel({
    persona,
    runId,
    className,
}: {
    persona: RunPersona
    runId: number
    className?: string
}) {
    const { text } = persona
    return (
        <FoldPanel
            label="Persona"
            what="instructions"
            className={className}
            data-testid="persona"
            readout={
                <span className="flex items-center gap-1">
                    <span className="readout text-xs">
                        {persona.name}
                        <span className="text-muted-foreground" title={persona.digest}>
                            {' '}
                            {persona.digest.slice(0, DIGEST_WIDTH)}
                        </span>
                        {persona.changed && <span className="text-muted-foreground">, edited since</span>}
                    </span>
                    {text !== null && <CopyButton text={text} label="persona" />}
                </span>
            }
        >
            {text === null ? (
                <Empty>its file cannot be read: {persona.problem ?? 'unreadable'}</Empty>
            ) : (
                <>
                    {persona.changed && (
                        <p className="border-b px-3 py-1.5 font-mono text-xs text-muted-foreground">
                            edited since run {runId} read it: this is its text now, not the one that run read
                        </p>
                    )}
                    <PanelScroll label="the persona's instructions">
                        <RichText text={text} prose className="p-3" />
                    </PanelScroll>
                </>
            )}
        </FoldPanel>
    )
}
