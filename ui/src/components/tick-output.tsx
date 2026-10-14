import { useQuery } from '@tanstack/react-query'
import { Braces } from 'lucide-react'
import { Fragment, useState } from 'react'

import { tickOutputQuery } from '@/api/queries'
import type { TickOutput } from '@/api/types'
import { JsonTokens } from '@/components/json-text'
import { Empty, Panel, PanelHeader, PanelScroll, PanelSkeleton } from '@/components/panel'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Toggle } from '@/components/ui/toggle'
import { jsonLines } from '@/lib/json-lines'
import { setPrettyOutput, usePrettyOutput } from '@/lib/pretty-output'
import { byteSize } from '@/lib/ticks'

/**
 * A tick's overseer output as written (DESIGN §22): its stdout, a `--- stderr ---` line, and its stderr, the lines
 * the transcript leaves out included. Hidden until the operator shows it, so a tick's page reads the file only when
 * asked; it opens at its end, where stderr is. All of it is agent output, rendered as text. Its JSON is one line an
 * event, as written, until the operator turns on pretty, which each tick's panel remembers (src/lib/pretty-output.ts).
 * `path` is where the file is, or null when the tick kept none.
 */
export function TickOutputPanel({ id, path, running }: { id: number; path: string | null; running: boolean }) {
    const [shown, setShown] = useState(false)
    const { data } = useQuery({ ...tickOutputQuery(id), enabled: shown && path !== null })
    const pretty = usePrettyOutput(id)
    return (
        <Collapsible asChild open={shown} onOpenChange={setShown}>
            <Panel data-testid="tick-output">
                <PanelHeader label="Output">
                    <span className="flex items-center gap-3">
                        {shown && data?.status === 'read' && (
                            <span className="readout text-xs text-muted-foreground">{byteSize(data.size)}</span>
                        )}
                        {shown && data?.status === 'read' && data.text !== '' && (
                            <Toggle
                                size="xs"
                                pressed={pretty}
                                onPressedChange={(on) => setPrettyOutput(id, on)}
                                title={
                                    pretty ? 'Show each event on one line, as written' : 'Lay each event out, indented'
                                }
                            >
                                <Braces />
                                Pretty
                            </Toggle>
                        )}
                        {path !== null && (
                            <CollapsibleTrigger asChild>
                                <Button variant="ghost" size="xs">
                                    {shown ? 'Hide' : 'Show'}
                                </Button>
                            </CollapsibleTrigger>
                        )}
                    </span>
                </PanelHeader>
                {path === null ? (
                    <Empty>{running ? 'no output yet: the overseer’s is written when it ends' : 'none kept'}</Empty>
                ) : (
                    <>
                        <CollapsibleContent>
                            {data === undefined ? <PanelSkeleton /> : <Body output={data} pretty={pretty} />}
                        </CollapsibleContent>
                        {!shown && (
                            <p className="px-3 py-2 font-mono text-xs text-muted-foreground">
                                <span className="break-all">{path}</span> as written: stdout, then stderr
                            </p>
                        )}
                    </>
                )}
            </Panel>
        </Collapsible>
    )
}

function Body({ output, pretty }: { output: TickOutput; pretty: boolean }) {
    if (output.status === 'no_output') {
        return <Empty>its output is gone, or is not a file canopy reads</Empty>
    }
    if (output.text === '') {
        return <Empty>empty: the overseer wrote nothing</Empty>
    }
    return (
        <>
            {output.truncated && (
                <p className="border-b px-3 py-1.5 font-mono text-xs text-muted-foreground">
                    cut: the file holds more, and this is its end, from a whole line
                </p>
            )}
            <PanelScroll
                label="the overseer's output"
                // Open at the end, where stderr and the session's last events are, and again on a switch to or from
                // pretty: it moves every line, so the place the operator had scrolled to is gone.
                key={pretty ? 'pretty' : 'compact'}
                ref={(el) => {
                    if (el) {
                        el.scrollTop = el.scrollHeight
                    }
                }}
                data-testid="tick-output-text"
            >
                <pre className="p-3 font-mono text-xs break-all whitespace-pre-wrap">
                    {jsonLines(output.text, pretty).map((tokens, i) => (
                        // A line's place is its identity: the text is read whole, never reordered.
                        <Fragment key={i}>
                            {i > 0 && '\n'}
                            <JsonTokens tokens={tokens} />
                        </Fragment>
                    ))}
                </pre>
            </PanelScroll>
        </>
    )
}
