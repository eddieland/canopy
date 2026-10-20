import type { Transcript } from '@/api/types'
import { CopyButton } from '@/components/copy-button'
import { FoldPanel } from '@/components/fold-panel'
import { LinkedText } from '@/components/linked-text'
import { Empty, Panel, PanelHeader, PanelScroll } from '@/components/panel'
import { byteSize } from '@/lib/ticks'

/**
 * The prompt that started a session (DESIGN §22), as canopy rendered it and kept it beside the log: what a run's, a
 * tick's, or a chore run's first model call was sent, after the agent's definition and the runtime's own system
 * prompt and tools, which no file records. It arrives folded, its length as its readout with a button that copies it
 * whole; `Show prompt` opens it from its start. It is read with the transcript, so its header waits on that read, and
 * with no prompt kept it is its header alone, saying so. Untrusted in part, since it quotes tickets, comments, and
 * PRs: rendered as text.
 */
export function PromptPanel({ transcript }: { transcript: Transcript | undefined }) {
    if (transcript === undefined) {
        return (
            <Panel data-testid="prompt">
                <PanelHeader label="Prompt" />
            </Panel>
        )
    }
    const { prompt } = transcript
    if (prompt === null) {
        return (
            <Panel data-testid="prompt">
                <PanelHeader label="Prompt">
                    <span
                        className="readout text-xs text-muted-foreground"
                        title="canopy kept no prompt beside this log: it was never written, or is gone"
                    >
                        none kept
                    </span>
                </PanelHeader>
            </Panel>
        )
    }
    const lines = lineCount(prompt.text)
    const bytes = new TextEncoder().encode(prompt.text).length
    const size = `${lines} ${lines === 1 ? 'line' : 'lines'} · ${byteSize(bytes)}`
    return (
        <FoldPanel
            label="Prompt"
            what="prompt"
            readout={
                <span className="flex items-center gap-1">
                    <span className="readout text-xs text-muted-foreground">
                        {prompt.truncated ? `${size}, cut` : size}
                    </span>
                    {prompt.text !== '' && <CopyButton text={prompt.text} label="prompt" />}
                </span>
            }
            data-testid="prompt"
        >
            {prompt.text === '' ? (
                <Empty>empty: canopy kept a prompt with nothing in it</Empty>
            ) : (
                <>
                    {prompt.truncated && (
                        <p className="border-b px-3 py-1.5 font-mono text-xs text-muted-foreground">
                            cut: the file holds more, and this is its start
                        </p>
                    )}
                    <PanelScroll label="the prompt">
                        <pre className="p-3 font-mono text-xs break-words whitespace-pre-wrap">
                            <LinkedText text={prompt.text} />
                        </pre>
                    </PanelScroll>
                </>
            )}
        </FoldPanel>
    )
}

/** How many lines `text` holds: a last line counts without its line break. */
function lineCount(text: string): number {
    if (text === '') {
        return 0
    }
    const breaks = text.split('\n').length - 1
    return text.endsWith('\n') ? breaks : breaks + 1
}
