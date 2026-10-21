import type { RunPersona } from '@/api/types'
import { CopyButton } from '@/components/copy-button'
import { FoldPanel } from '@/components/fold-panel'
import { Empty, PanelScroll } from '@/components/panel'
import { DIGEST_WIDTH } from '@/components/persona-field'
import { RichText } from '@/components/rich-text'

/**
 * The persona a run wrote in (DESIGN §31), and the instructions it read: its name and the start of its digest as the
 * readout, as `PersonaField` shows them, and `Show instructions` opening the text the journal kept for that digest.
 * When canopy cannot tell what the run read, it says why in the text's place. Laid out as the Markdown it is, its
 * wrapped lines joined, and rendered as React text.
 */
export function PersonaPanel({ persona, className }: { persona: RunPersona; className?: string }) {
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
                    </span>
                    {text !== null && <CopyButton text={text} label="persona" />}
                </span>
            }
        >
            {text === null ? (
                <Empty>no text: {persona.problem ?? 'canopy kept none'}</Empty>
            ) : (
                <PanelScroll label="the persona's instructions">
                    <RichText text={text} prose className="p-3" />
                </PanelScroll>
            )}
        </FoldPanel>
    )
}
