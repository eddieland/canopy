import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'

import { tickOutputQuery } from '@/api/queries'
import type { TickOutput } from '@/api/types'
import { JsonTokens } from '@/components/json-text'
import { Panel, PanelHeader, PanelScroll, Placeholder } from '@/components/panel'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { jsonLines } from '@/lib/json-lines'
import { byteSize } from '@/lib/ticks'

/**
 * A tick's overseer output as written (DESIGN §22): its stdout, a `--- stderr ---` line, and its stderr, the lines
 * the transcript leaves out included. Hidden until the operator shows it, so a tick's page reads the file only when
 * asked; it opens at its end, where stderr is. All of it is agent output, rendered as text. `path` is where the file
 * is, or null when the tick kept none.
 */
export function TickOutputPanel({ id, path, running }: { id: number; path: string | null; running: boolean }) {
    const [shown, setShown] = useState(false)
    const { data } = useQuery({ ...tickOutputQuery(id), enabled: shown && path !== null })
    return (
        <Panel data-testid="tick-output">
            <PanelHeader label="Output">
                <span className="flex items-center gap-3">
                    {shown && data?.status === 'read' && (
                        <span className="readout text-xs text-muted-foreground">{byteSize(data.size)}</span>
                    )}
                    {path !== null && (
                        <Button variant="ghost" size="xs" aria-expanded={shown} onClick={() => setShown((s) => !s)}>
                            {shown ? 'Hide' : 'Show'}
                        </Button>
                    )}
                </span>
            </PanelHeader>
            {path === null ? (
                <Placeholder className="min-h-20">
                    {running ? 'the overseer’s output is written when it ends' : 'none kept'}
                </Placeholder>
            ) : !shown ? (
                <p className="px-3 py-2 font-mono text-xs text-muted-foreground">
                    <span className="break-all">{path}</span> as written: stdout, then stderr
                </p>
            ) : data === undefined ? (
                <div className="flex flex-col gap-2 p-3">
                    <Skeleton className="h-4 w-2/3" />
                    <Skeleton className="h-4 w-1/2" />
                </div>
            ) : (
                <Body output={data} />
            )}
        </Panel>
    )
}

function Body({ output }: { output: TickOutput }) {
    if (output.status === 'no_output') {
        return <Placeholder className="min-h-20">its output is gone, or is not a file canopy reads</Placeholder>
    }
    if (output.text === '') return <Placeholder className="min-h-20">empty</Placeholder>
    return (
        <>
            {output.truncated && (
                <p className="border-b px-3 py-1.5 font-mono text-xs text-muted-foreground">
                    cut: the file holds more, and this is its end, from a whole line
                </p>
            )}
            <PanelScroll
                label="the overseer's output"
                // Open at the end, where stderr and the session's last events are.
                ref={(el) => {
                    if (el) el.scrollTop = el.scrollHeight
                }}
                data-testid="tick-output-text"
            >
                <pre className="p-3 font-mono text-xs break-all whitespace-pre-wrap">
                    {jsonLines(output.text).map((tokens, i) => (
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
