import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpFromLine, Eraser, RefreshCw, X } from 'lucide-react'
import { useId, useState } from 'react'
import type { ReactNode, SubmitEvent } from 'react'

import { forgetMemory, promoteMemory, refreshMemory, rejectMemory, renewMemory } from '@/api/mutations'
import { memoryQuery } from '@/api/queries'
import type { MemoryEntry } from '@/api/types'
import { Input, Textarea } from '@/components/input'
import { MemoryText } from '@/components/memory'
import { Notice } from '@/components/notice'
import { InlineCode } from '@/components/rich-text'
import { RowLine } from '@/components/rows'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { lessonChars, MAX_LESSON_CHARS, repoChoices } from '@/lib/memory'
import { memoryForgottenText, PRIVATE_WORDS, promotedText, rejectedText, renewedText } from '@/lib/outcomes'
import { memoryRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

// The operator's verbs on agent memory from the page that shows it (DESIGN §28, ROADMAP M52): each the function its
// `canopy memory` verb calls, with its guards. A verb's row can leave once it is done (a promoted or rejected
// proposal, a forgotten lesson), so what it did is said under the list it was done from (`onSaid`), and only its
// refusal under the row, which stays.

// The repository choice that stands for every one: no repository's name, which the workspace map holds to lowercase
// letters, digits, and hyphens. Not '': a segmented control takes that for nothing picked.
const EVERY = '*'

/** What a list of memories hands its rows' actions: where to say what one did, under the list. */
interface Said {
    /** Says what a verb did, in the CLI's words, under the list the row is in. */
    onSaid: (said: string) => void
}

/**
 * What the last verb done from a list of memories did, in the CLI's words, its `code` spans set as code; nothing
 * before one. It sits under the list's band, since the row it was done from may have left the list.
 */
export function MemorySaid({ said, className }: { said: string | null; className?: string }) {
    return <Notice className={className}>{said === null ? null : <InlineCode text={said} links={false} />}</Notice>
}

/**
 * A proposal's verbs, under its row: Promote, which opens the form for the lesson's words and repository, and
 * Reject. With `asWritten`, as on an attention item, Promote makes the lesson at once, in the proposal's own words and
 * for its repository, as `canopy memory promote ID` does.
 */
export function ProposalActions({
    proposal,
    asWritten = false,
    onSaid,
}: Said & { proposal: MemoryEntry; asWritten?: boolean }) {
    const client = useQueryClient()
    const [open, setOpen] = useState(false)
    const promote = useMutation({
        mutationFn: () => promoteMemory(proposal.id, { text: null, repo: null }),
        onSuccess: (promoted) => {
            onSaid(promotedText(promoted))
            void refreshMemory(client)
        },
    })
    const reject = useMutation({
        mutationFn: () => rejectMemory(proposal.id),
        onSuccess: (rejected) => {
            onSaid(rejectedText(rejected.id))
            void refreshMemory(client)
        },
    })
    const pending = promote.isPending || reject.isPending
    return (
        <RowLine from="key" className="flex flex-col gap-2">
            {!open && (
                <span className="flex flex-wrap items-center gap-2">
                    <Button
                        variant="outline"
                        size="xs"
                        title={`canopy memory promote ${proposal.id}`}
                        onClick={() => (asWritten ? promote.mutate() : setOpen(true))}
                        disabled={pending}
                    >
                        <ArrowUpFromLine />
                        {asWritten ? 'Promote as written' : 'Promote'}
                    </Button>
                    <Button
                        variant="ghost"
                        size="xs"
                        className="text-muted-foreground"
                        title={`canopy memory reject ${proposal.id}`}
                        onClick={() => reject.mutate()}
                        disabled={pending}
                    >
                        <X />
                        Reject
                    </Button>
                </span>
            )}
            {open && <PromoteForm source={proposal} onSaid={onSaid} onClose={() => setOpen(false)} />}
            <Notice error={promote.error ?? reject.error} />
        </RowLine>
    )
}

/** A ticket's note's verb, under its row, while it keeps its text: Promote, which opens the form for the lesson. */
export function NoteActions({ note, onSaid }: Said & { note: MemoryEntry }) {
    const [open, setOpen] = useState(false)
    if (note.text === null) {
        return null
    }
    return (
        <RowLine from="key">
            {open ? (
                <PromoteForm source={note} onSaid={onSaid} onClose={() => setOpen(false)} />
            ) : (
                <Button
                    variant="outline"
                    size="xs"
                    title={`canopy memory promote ${note.id}`}
                    onClick={() => setOpen(true)}
                >
                    <ArrowUpFromLine />
                    Promote
                </Button>
            )}
        </RowLine>
    )
}

/**
 * A lesson's verbs, under its row: Renew, and Forget, which cannot be undone and so asks for the lesson's ref typed.
 * Until then Forget is the quieter, at the line's end. With `forget` false, as on a `lesson_review` item, Renew alone.
 */
export function LessonActions({ lesson, forget = true, onSaid }: Said & { lesson: MemoryEntry; forget?: boolean }) {
    const client = useQueryClient()
    const [confirming, setConfirming] = useState(false)
    const renew = useMutation({
        mutationFn: () => renewMemory(lesson.id),
        onSuccess: (renewed) => {
            onSaid(renewedText(renewed))
            void refreshMemory(client)
        },
    })
    return (
        <RowLine from="key" className="flex flex-col gap-2">
            <span className="flex flex-wrap items-center gap-2">
                <Button
                    variant="outline"
                    size="xs"
                    title={`canopy memory renew ${lesson.id}`}
                    onClick={() => renew.mutate()}
                    disabled={renew.isPending}
                >
                    <RefreshCw />
                    Renew
                </Button>
                {forget && !confirming && (
                    <Button
                        variant="ghost"
                        size="xs"
                        className="ml-auto text-status-failed hover:text-status-failed"
                        onClick={() => setConfirming(true)}
                        disabled={renew.isPending}
                    >
                        <Eraser />
                        Forget
                    </Button>
                )}
            </span>
            {confirming && (
                <ForgetChallenge memory={lesson} onSaid={onSaid} onCancel={() => setConfirming(false)}>
                    canopy deletes this lesson&apos;s text, and no run reads it again. Its row stays, saying who
                    promoted it and when. This cannot be undone: promote its proposal or note again to have it back.
                </ForgetChallenge>
            )}
            <Notice error={renew.error} />
        </RowLine>
    )
}

/**
 * The lesson a promote would make: its text, starting as the source's own and held to the bound a proposal is, and
 * the repository whose runs it is served to, the source's or every one for a note. Before the save it says which
 * lesson in force under the key it would replace, and, while the text is still a private ticket's run's own words,
 * the warning `canopy memory promote` gives. It reads the lessons in force, and the workspace's repositories, when it
 * opens (`memoryQuery`, which the memory page has already read).
 */
export function PromoteForm({ source, onSaid, onClose }: Said & { source: MemoryEntry; onClose: () => void }) {
    const client = useQueryClient()
    const id = useId()
    const own = source.text ?? ''
    const [text, setText] = useState(own)
    const [repo, setRepo] = useState(source.repo)
    const { data } = useQuery(memoryQuery)
    const promote = useMutation({
        mutationFn: () =>
            promoteMemory(source.id, {
                // The source's own words and repository go as null, as the CLI leaves --text and --repo out: the
                // server trims the text, so only spaces at either end changed still leaves the words the run's.
                text: text.trim() === own.trim() ? null : text,
                repo: repo === source.repo ? null : repo,
            }),
        onSuccess: (promoted) => {
            onSaid(promotedText(promoted))
            onClose()
            void refreshMemory(client)
        },
    })
    const chars = lessonChars(text)
    const fits = chars > 0 && chars <= MAX_LESSON_CHARS
    const replaced = data?.lessons.find((m) => m.key === source.key)
    const privateWords = source.private && text.trim() === own.trim()

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (fits) {
            promote.mutate()
        }
    }

    return (
        <form
            onSubmit={submit}
            aria-label={`Promote ${memoryRef(source.id)}`}
            className="flex flex-col gap-2 rounded-md border bg-surface p-3"
        >
            <span className="flex items-baseline justify-between gap-3">
                <label className="panel-label" htmlFor={`${id}-text`}>
                    The lesson, in your words
                </label>
                <span
                    className={cn('readout text-xs text-muted-foreground', !fits && chars > 0 && 'text-status-failed')}
                    data-testid="lesson-chars"
                >
                    {chars} of {MAX_LESSON_CHARS}
                </span>
            </span>
            <Textarea
                id={`${id}-text`}
                value={text}
                onChange={(event) => setText(event.target.value)}
                spellCheck
                className="min-h-20"
            />
            {data !== undefined && (
                <span className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-muted-foreground" id={`${id}-repo`}>
                        Served to runs in
                    </span>
                    <ToggleGroup
                        type="single"
                        value={repo ?? EVERY}
                        aria-labelledby={`${id}-repo`}
                        onValueChange={(value) => {
                            // A radio group keeps one picked: pressing the picked one again leaves it, as ''.
                            if (value !== '') {
                                setRepo(value === EVERY ? null : value)
                            }
                        }}
                        className="flex-wrap"
                    >
                        {repoChoices(source, data.repos).map((name) => (
                            <ToggleGroupItem
                                key={name ?? EVERY}
                                value={name ?? EVERY}
                                className={cn(name && 'font-mono')}
                            >
                                {name ?? 'every repository'}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                </span>
            )}
            {/* Reserved while the lessons are read, so the line that names the one replaced moves nothing in. */}
            <p className="min-h-4 text-xs text-muted-foreground" data-testid="promote-replaces">
                {data === undefined ? (
                    'Reading the lessons in force.'
                ) : replaced === undefined ? (
                    <>
                        No lesson is in force under <code className="font-mono">{source.key}</code>: it replaces none.
                    </>
                ) : (
                    <>
                        It replaces {memoryRef(replaced.id)}, the lesson in force under{' '}
                        <code className="font-mono">{source.key}</code>
                        {replaced.text !== null && (
                            <>
                                : <MemoryText text={replaced.text} className="text-foreground" />
                            </>
                        )}
                    </>
                )}
            </p>
            {privateWords && (
                <p className="text-xs text-status-blocked" data-testid="promote-private">
                    {PRIVATE_WORDS}
                </p>
            )}
            <span className="flex flex-wrap items-center gap-2">
                <Button type="submit" disabled={promote.isPending || !fits}>
                    <ArrowUpFromLine />
                    Promote {memoryRef(source.id)}
                </Button>
                <Button type="button" variant="ghost" onClick={onClose} disabled={promote.isPending}>
                    Cancel
                </Button>
            </span>
            <Notice error={promote.error} />
        </form>
    )
}

/**
 * What forgetting does, in `children`, and a field the memory's ref (`memory:8`) must be typed into before the button
 * that forgets is enabled, as a ticket's Forget asks for its key.
 */
function ForgetChallenge({
    memory,
    onSaid,
    onCancel,
    children,
}: Said & { memory: MemoryEntry; onCancel: () => void; children: ReactNode }) {
    const client = useQueryClient()
    const id = useId()
    const ref = memoryRef(memory.id)
    const [typed, setTyped] = useState('')
    const forget = useMutation({
        mutationFn: () => forgetMemory(memory.id, typed),
        onSuccess: (forgot) => {
            onSaid(memoryForgottenText(forgot))
            void refreshMemory(client)
        },
    })
    const matches = typed === ref

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (matches) {
            forget.mutate()
        }
    }

    return (
        <form
            onSubmit={submit}
            aria-label={`Forget ${ref}`}
            className="flex flex-col gap-2 rounded-md border border-status-failed/40 bg-status-failed/5 p-3"
        >
            <p className="text-xs text-foreground">{children}</p>
            <label className="panel-label" htmlFor={`${id}-confirm`}>
                Type {ref} to confirm
            </label>
            <span className="flex flex-wrap items-center gap-2">
                <Input
                    id={`${id}-confirm`}
                    value={typed}
                    onChange={(event) => setTyped(event.target.value)}
                    placeholder={ref}
                    autoComplete="off"
                    spellCheck={false}
                    className="max-w-56 font-mono"
                />
                <Button type="submit" variant="destructive" disabled={forget.isPending || !matches}>
                    <Eraser />
                    Forget {ref}
                </Button>
                <Button type="button" variant="ghost" onClick={onCancel} disabled={forget.isPending}>
                    Keep it
                </Button>
            </span>
            <Notice error={forget.error} />
        </form>
    )
}
