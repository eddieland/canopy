import type { RunMessage } from '@/api/types'
import { Age } from '@/components/age'
import { Panel, PanelHeader } from '@/components/panel'
import { ReplyForm } from '@/components/reply-form'
import { RichText } from '@/components/rich-text'
import { messageRef } from '@/lib/refs'

/**
 * Where a message to a run goes: a worker's or planner's run itself, `run:ID`, or a task's run through a reply to its
 * task, which reaches the run while it runs (DESIGN §44).
 */
export type MessageTarget = { kind: 'run'; id: number } | { kind: 'task'; id: number }

/**
 * The operator's messages to a run while it ran (DESIGN §44), oldest first, each with when its agent fetched it through
 * canopy's tool, as `canopy show run:ID` lists them; and while it runs, the form for another. Its agent hears on its
 * next tool call that one waits, never its words. An ended run that was sent none shows nothing, and an ended run takes
 * no more: its subject's reply reaches its next run instead.
 */
export function RunMessagesPanel({
    messages,
    running,
    target,
}: {
    messages: RunMessage[]
    running: boolean
    target: MessageTarget
}) {
    if (!running && messages.length === 0) {
        return null
    }
    const fetched = messages.filter((message) => message.fetched_at !== null).length
    const said = messages.length === 0 ? 'none sent' : `${messages.length} sent · ${fetched} fetched`
    return (
        <Panel aria-label="Messages to it">
            <PanelHeader label="Messages">
                <span className="readout text-xs text-muted-foreground">{said}</span>
            </PanelHeader>
            {messages.length > 0 && (
                <ol className="flex flex-col divide-y" aria-label="Your messages to it">
                    {messages.map((message) => (
                        <li key={message.id} className="flex flex-col gap-1 px-3 py-2">
                            <span className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
                                <span className="readout">{messageRef(message.id)}</span>
                                <span>
                                    sent <Age at={message.at} variant="ago" />
                                </span>
                                <Fetched message={message} running={running} />
                            </span>
                            <RichText text={message.body} />
                        </li>
                    ))}
                </ol>
            )}
            {running && (
                <ReplyForm
                    key={`${target.kind}:${target.id}`}
                    target={target.kind === 'run' ? target : { ...target, running: true }}
                    className={messages.length === 0 ? 'border-t-0' : undefined}
                />
            )}
        </Panel>
    )
}

/**
 * Whether the run's agent fetched a message, in the words `canopy show` uses: when it did, that it has not yet, or,
 * once the run has ended, never did. One canopy could not write where its agent reads it says so.
 */
function Fetched({ message, running }: { message: RunMessage; running: boolean }) {
    if (message.fetched_at !== null) {
        return (
            <span>
                fetched <Age at={message.fetched_at} variant="ago" />
            </span>
        )
    }
    if (message.delivered_at === null) {
        return <span>not written where its agent reads it{running ? ' yet' : ''}</span>
    }
    return <span>{running ? 'not fetched yet' : 'never fetched'}</span>
}
