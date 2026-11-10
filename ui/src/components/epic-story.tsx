import type { EpicDetail, EpicPlanRun, Message } from '@/api/types'
import { Bubble, HeadLine, InstructionBubble, Who } from '@/components/conversation'
import { OrderToggle } from '@/components/order-toggle'
import { PanelHeader, ThreadScroll } from '@/components/panel'
import { Chip } from '@/components/status'
import { BUBBLE_TONE, OPEN_QUESTION } from '@/lib/bubble-tone'
import { ordered, useListOrder } from '@/lib/list-order'
import { epicRef, epicRunRef, messageAnchor, messageRef } from '@/lib/refs'

/** One turn of an epic's story after its goal: a reply of the operator's, or what one of its plan runs said. */
type Turn = { at: string; message: Message; run?: undefined } | { at: string; run: EpicPlanRun; message?: undefined }

/**
 * An epic's story (DESIGN §43), inside its Conversation panel: the operator's goal at its oldest end, in their own
 * words, then what each plan run said and the operator's replies, in time, in the operator's order, as a task's story
 * reads. A plan run's words are the planner's summary or the harness's note on how it ended, or the question it asked,
 * which wears `waiting on you` while no reply has followed it. Every body is untrusted text. Replying is the plan's
 * page's, so the panel has no form.
 */
export function EpicStory({ detail }: { detail: EpicDetail }) {
    const { epic } = detail
    const order = useListOrder('conversation')
    const turns = story(detail)
    const waiting = asking(detail)
    return (
        <>
            <PanelHeader label="Conversation">
                <span className="flex items-center gap-2">
                    {turns.length > 0 && <OrderToggle list="conversation" />}
                    <span className="readout text-xs text-muted-foreground">{turns.length + 1}</span>
                </span>
            </PanelHeader>
            <ThreadScroll key={`thread-${epic.id}`} label="Conversation" end={order === 'oldest' ? 'bottom' : 'top'}>
                <ol className="flex stagger flex-col gap-3 p-3" data-testid="conversation">
                    {order === 'oldest' && <Goal detail={detail} />}
                    {ordered('conversation', order, turns).map((turn) =>
                        turn.message === undefined ? (
                            <RunTurn
                                key={`run-${turn.run.id}`}
                                epic={epic.id}
                                run={turn.run}
                                open={turn.run === waiting}
                            />
                        ) : (
                            <Bubble
                                key={`message-${turn.message.id}`}
                                id={messageAnchor(turn.message.id)}
                                data-testid={messageAnchor(turn.message.id)}
                                data-source="operator"
                                operator
                                tone={BUBBLE_TONE.reply}
                                body={turn.message.body}
                                head={
                                    <HeadLine name={messageRef(turn.message.id)} at={turn.message.at} operator>
                                        <Who>you</Who>
                                        <span>reply via {turn.message.channel}</span>
                                    </HeadLine>
                                }
                            />
                        ),
                    )}
                    {order === 'newest' && <Goal detail={detail} />}
                </ol>
            </ThreadScroll>
        </>
    )
}

/** The epic's goal, the operator's words that head its story, as a task's instruction does. */
function Goal({ detail }: { detail: EpicDetail }) {
    const { epic } = detail
    return (
        <InstructionBubble
            instruction={{ ref: epicRef(epic.id), at: epic.submitted_at, body: epic.text, channel: epic.channel }}
        />
    )
}

/** What one plan run said, on the planner's side: its question, or else its summary, named `epic:2#3`. */
function RunTurn({ epic, run, open }: { epic: number; run: EpicPlanRun; open: boolean }) {
    const question = run.question ?? null
    return (
        <Bubble
            data-testid={`plan-run-${String(run.id)}`}
            data-source="worker"
            operator={false}
            tone={open ? OPEN_QUESTION : BUBBLE_TONE[question === null ? 'report' : 'question']}
            body={question ?? run.summary ?? ''}
            head={
                <HeadLine name={epicRunRef(epic, run.id)} at={run.ended_at ?? run.started_at} operator={false}>
                    <Who>planner</Who>
                    <span>{question === null ? 'report' : 'question'}</span>
                    {open && <Chip tone="blocked">waiting on you</Chip>}
                </HeadLine>
            }
        />
    )
}

/**
 * The epic's story after its goal, oldest first, as the server sends each list: its replies, and each plan run that
 * said anything, at when it ended. A run still working has said nothing yet.
 */
function story({ messages, runs }: Pick<EpicDetail, 'messages' | 'runs'>): Turn[] {
    const said: Turn[] = runs
        .filter((run) => (run.question ?? run.summary ?? '') !== '')
        .map((run) => ({ at: run.ended_at ?? run.started_at, run }))
    const replies: Turn[] = messages.map((message) => ({ at: message.at, message }))
    return [...said, ...replies].toSorted((a, b) => Date.parse(a.at) - Date.parse(b.at))
}

/** The plan run whose question waits on the operator: the newest run, which asked one, with no reply after it. */
function asking({ messages, runs }: Pick<EpicDetail, 'messages' | 'runs'>): EpicPlanRun | undefined {
    const last = runs.at(-1)
    const ended = last?.question === null ? null : (last?.ended_at ?? null)
    if (last === undefined || ended === null) {
        return undefined
    }
    const asked = Date.parse(ended)
    return messages.some((message) => Date.parse(message.at) >= asked) ? undefined : last
}
