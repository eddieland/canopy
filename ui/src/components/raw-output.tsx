import { useQuery } from '@tanstack/react-query'
import type { QueryKey, UseQueryOptions } from '@tanstack/react-query'
import { Braces } from 'lucide-react'
import { Fragment, useState } from 'react'

import { runOutputQuery, tickOutputQuery } from '@/api/queries'
import type { RawOutput } from '@/api/types'
import { Disclosure } from '@/components/disclosure'
import { JsonTokens } from '@/components/json-text'
import { Empty, Panel, PanelHeader, PanelScroll, PanelSkeleton } from '@/components/panel'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { Toggle } from '@/components/ui/toggle'
import { jsonLines } from '@/lib/json-lines'
import { setPrettyOutput, usePrettyOutput } from '@/lib/pretty-output'
import { byteSize } from '@/lib/ticks'

/**
 * A tick's overseer output as written (DESIGN §22): its stdout, a `--- stderr ---` line, and its stderr, the lines
 * the transcript leaves out included. Its JSON is one line an event, as written, until the operator turns on pretty,
 * which each tick's panel remembers (src/lib/pretty-output.ts). `path` is where the file is, or null when the tick kept
 * none: its overseer has not started, or never ran.
 */
export function TickOutputPanel({ id, path, running }: { id: number; path: string | null; running: boolean }) {
    const pretty = usePrettyOutput(id)
    return (
        <OutputPanel
            query={tickOutputQuery(id)}
            file={path}
            none={running ? 'no output yet: the overseer has not started' : 'no output kept'}
            whose="the overseer"
            written="stdout, then stderr"
            pretty={pretty}
            onPretty={(on) => setPrettyOutput(id, on)}
            testId="tick-output"
        />
    )
}

/**
 * A run's log as written (DESIGN §22): its setup commands' output, then its worker's stdout, stderr, and exit, each
 * under a `--- ... ---` line canopy writes, so a run that failed before its first event says why. Pretty is the page's
 * alone, not remembered: a tick's panel is the one read again and again.
 */
export function RunOutputPanel({ id }: { id: number }) {
    const [pretty, setPretty] = useState(false)
    return (
        <OutputPanel
            query={runOutputQuery(id)}
            // Its path is the Run panel's log field, with its copy button: named once.
            file="the run’s log"
            none="no log kept"
            whose="the run"
            written="its setup commands’ output, then the worker’s stdout and stderr"
            pretty={pretty}
            onPretty={setPretty}
            testId="run-output"
        />
    )
}

/**
 * The end of a file of agent output as written, hidden until the operator shows it, so a page reads the file only when
 * asked; it opens at its end, where stderr is. All of it is agent output, rendered as text. `file` names it while
 * hidden, or is null when there is none to show.
 */
function OutputPanel<K extends QueryKey>({
    query,
    file,
    none,
    whose,
    written,
    pretty,
    onPretty,
    testId,
}: {
    query: UseQueryOptions<RawOutput, Error, RawOutput, K>
    file: string | null
    none: string
    whose: string
    written: string
    pretty: boolean
    onPretty: (on: boolean) => void
    testId: string
}) {
    const [shown, setShown] = useState(false)
    const { data } = useQuery({ ...query, enabled: shown && file !== null })
    return (
        <Collapsible asChild open={shown} onOpenChange={setShown}>
            <Panel data-testid={testId}>
                <PanelHeader label="Output">
                    <span className="flex items-center gap-3">
                        {shown && data?.status === 'read' && (
                            <span className="readout text-xs text-muted-foreground">{byteSize(data.size)}</span>
                        )}
                        {shown && data?.status === 'read' && data.text !== '' && (
                            <Toggle
                                size="xs"
                                pressed={pretty}
                                onPressedChange={onPretty}
                                title={
                                    pretty ? 'Show each event on one line, as written' : 'Lay each event out, indented'
                                }
                            >
                                <Braces />
                                Pretty
                            </Toggle>
                        )}
                        {file !== null && <Disclosure open={shown} what="output" />}
                    </span>
                </PanelHeader>
                {file === null ? (
                    <Empty>{none}</Empty>
                ) : (
                    <>
                        <CollapsibleContent>
                            {data === undefined ? (
                                <PanelSkeleton />
                            ) : (
                                <Body output={data} pretty={pretty} whose={whose} testId={testId} />
                            )}
                        </CollapsibleContent>
                        {!shown && (
                            <p className="px-3 py-2 font-mono text-xs text-muted-foreground">
                                <span className="break-all">{file}</span> as written: {written}
                            </p>
                        )}
                    </>
                )}
            </Panel>
        </Collapsible>
    )
}

function Body({
    output,
    pretty,
    whose,
    testId,
}: {
    output: RawOutput
    pretty: boolean
    whose: string
    testId: string
}) {
    if (output.status === 'no_output') {
        return <Empty>its output is gone, or is not a file canopy reads</Empty>
    }
    if (output.text === '') {
        return <Empty>empty: {whose} wrote nothing</Empty>
    }
    return (
        <>
            {output.truncated && (
                <p className="border-b px-3 py-1.5 font-mono text-xs text-muted-foreground">
                    cut: the file holds more, and this is its end, from a whole line
                </p>
            )}
            <PanelScroll
                label={`${whose}'s output`}
                // Open at the end, where stderr and the session's last events are, and again on a switch to or from
                // pretty: it moves every line, so the place the operator had scrolled to is gone.
                key={pretty ? 'pretty' : 'compact'}
                ref={(el) => {
                    if (el) {
                        el.scrollTop = el.scrollHeight
                    }
                }}
                data-testid={`${testId}-text`}
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
