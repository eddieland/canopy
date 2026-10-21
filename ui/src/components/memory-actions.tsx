import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { ArrowUpFromLine, Eraser, Pencil, RefreshCw, X } from 'lucide-react'
import { useId, useState } from 'react'
import type { ReactNode, SubmitEvent } from 'react'

import { ApiError } from '@/api/client'
import { editMemory, forgetMemory, promoteMemory, refreshMemory, rejectMemory, renewMemory } from '@/api/mutations'
import { memoryQuery } from '@/api/queries'
import type { MemoryEntry } from '@/api/types'
import { ForgetForm } from '@/components/forget-form'
import { Textarea } from '@/components/input'
import { MemoryText } from '@/components/memory-text'
import { Notice } from '@/components/notice'
import { InlineCode } from '@/components/rich-text'
import { RepoSelect } from '@/components/repo-picker'
import { RowLine } from '@/components/rows'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { editRepoChoices, lessonChars, MAX_LESSON_CHARS, memoryStand, repoChoices } from '@/lib/memory'
import { editedText, memoryForgottenText, PRIVATE_WORDS, promotedText, rejectedText, renewedText } from '@/lib/outcomes'
import { memoryRef } from '@/lib/refs'
import { useSendKeys } from '@/lib/send-key'
import type { SendKeys } from '@/lib/send-key'
import { useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

// The operator's verbs on agent memory from the page that shows it (DESIGN §28, ROADMAP M52): each the function its
// `canopy memory` verb calls, with its guards. A verb's row can leave once it is done (a promoted or rejected
// proposal, a forgotten lesson), so what it did is said under the list it was done from (`onSaid`), and only its
// refusal under the row, which stays.

// The refusals that mean the memory is not as the page last read it.
const STALE: ReadonlySet<string> = new Set(['not_pending', 'forgotten', 'unknown'])

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
 * A proposal's verbs, under its row: Promote as written, the outline, which makes the lesson at once in the proposal's
 * own words and for its repository, as `canopy memory promote ID` does, since most proposals need no edit; Edit and
 * promote, which opens the form for the lesson's words and repository; and at the line's end, apart from both, Reject,
 * and Forget, for a proposal whose text must go and not merely be declined. With `edit` false, as on an attention
 * item, no Edit and promote; with `forget` false, as there, no Forget. Two proposals are never promoted in one click,
 * since the form says what the click would not before the save: a private ticket's run's, whose words may hold what the
 * operator kept off the tracker, and one whose key a lesson in force has, which the promote replaces. Their first
 * button opens the form, and where there is no form the line says to promote them from the memory page. It reads the
 * lessons in force to tell (`memoryQuery`, which the memory page has already read), and promotes nothing until then;
 * when that read fails, the line says so and to promote it from the memory page.
 */
export function ProposalActions({
    proposal,
    edit = true,
    forget = true,
    onSaid,
}: Said & { proposal: MemoryEntry; edit?: boolean; forget?: boolean }) {
    const client = useQueryClient()
    const [open, setOpen] = useState(false)
    const [confirming, setConfirming] = useState(false)
    const promote = useMutation({
        mutationFn: () => promoteMemory(proposal.id, { text: null, repo: null }),
        onSuccess: (promoted) => {
            onSaid(promotedText(promoted))
            void refreshMemory(client)
        },
        onError: (error) => void refreshIfStale(client, error, onSaid),
    })
    const reject = useMutation({
        mutationFn: () => rejectMemory(proposal.id),
        onSuccess: (rejected) => {
            onSaid(rejectedText(rejected.id))
            void refreshMemory(client)
        },
        onError: (error) => void refreshIfStale(client, error, onSaid),
    })
    const pending = promote.isPending || reject.isPending
    const { data, isError } = useQuery(memoryQuery)
    const replaced = data === undefined ? undefined : inForceUnder(data.lessons, proposal.key)
    const viaForm = proposal.private || replaced !== undefined
    // What the button that opens the form says on hover, read only while `viaForm`.
    const formTitle =
        proposal.private || replaced === undefined
            ? "A private ticket's run wrote it: the form warns before you save"
            : `It replaces ${memoryRef(replaced.id)}: the form shows that lesson before you save`
    return (
        <RowLine from="key" className="flex flex-col gap-2">
            {!open && (
                <span className="flex flex-wrap items-center gap-2">
                    {viaForm && edit ? (
                        <Button
                            variant="outline"
                            size="xs"
                            title={formTitle}
                            onClick={() => setOpen(true)}
                            disabled={pending}
                        >
                            <ArrowUpFromLine />
                            Promote
                        </Button>
                    ) : proposal.private ? (
                        <span className="text-xs text-muted-foreground" data-testid="promote-private-elsewhere">
                            private: promote it from the memory page, where the form warns first
                        </span>
                    ) : data === undefined && isError ? (
                        // A disabled button shows no title, so a failed read says why in the line.
                        <span className="text-xs text-muted-foreground" data-testid="promote-unread">
                            the lessons in force could not be read: promote it from the memory page
                        </span>
                    ) : replaced === undefined ? (
                        <Button
                            variant="outline"
                            size="xs"
                            title={`canopy memory promote ${proposal.id}`}
                            onClick={() => promote.mutate()}
                            // Until the lessons in force are read, whether it replaces one is not known.
                            disabled={pending || data === undefined}
                        >
                            <ArrowUpFromLine />
                            Promote as written
                        </Button>
                    ) : (
                        <span className="text-xs text-muted-foreground" data-testid="promote-replaces-elsewhere">
                            replaces {memoryRef(replaced.id)}: promote it from the memory page, where the form shows
                            both
                        </span>
                    )}
                    {replaced !== undefined && edit && (
                        <span className="text-xs text-muted-foreground" data-testid="proposal-replaces">
                            replaces {memoryRef(replaced.id)}
                        </span>
                    )}
                    {edit && !viaForm && (
                        <Button
                            variant="ghost"
                            size="xs"
                            className="text-muted-foreground"
                            title={`canopy memory promote ${proposal.id} --text TEXT --repo REPO`}
                            onClick={() => setOpen(true)}
                            disabled={pending}
                        >
                            <Pencil />
                            Edit and promote
                        </Button>
                    )}
                    {/* Reject cannot be undone: it stands apart from the promotes, at the line's end with Forget. */}
                    <span className="ml-auto flex items-center gap-2">
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
                        {forget && !confirming && (
                            <ForgetButton memory={proposal} onClick={() => setConfirming(true)} disabled={pending} />
                        )}
                    </span>
                </span>
            )}
            {open && <PromoteForm source={proposal} onSaid={onSaid} onClose={() => setOpen(false)} />}
            {confirming && (
                <ForgetChallenge memory={proposal} onSaid={onSaid} onCancel={() => setConfirming(false)}>
                    canopy deletes this proposal&apos;s text, and it leaves the queue unpromoted. Its row stays, saying
                    which run proposed it. This cannot be undone: Reject is enough, unless the words themselves must go.
                </ForgetChallenge>
            )}
            <Notice error={promote.error ?? reject.error} />
        </RowLine>
    )
}

/**
 * A ticket's note's verbs, under its row, while it keeps its text: Promote, which opens the form for the lesson, and
 * at the line's end Forget, which cannot be undone and so asks for the note's ref typed. With `promote` false, while
 * lessons are off, Forget alone: a note holding what should not be kept is forgotten from where it shows, whatever
 * lessons' mode (DESIGN §28).
 */
export function NoteActions({ note, promote = true, onSaid }: Said & { note: MemoryEntry; promote?: boolean }) {
    const [open, setOpen] = useState(false)
    const [confirming, setConfirming] = useState(false)
    if (note.text === null) {
        return null
    }
    return (
        <RowLine from="key" className="flex flex-col gap-2">
            {open ? (
                <PromoteForm source={note} onSaid={onSaid} onClose={() => setOpen(false)} />
            ) : (
                <span className="flex flex-wrap items-center gap-2">
                    {promote && (
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
                    {!confirming && <ForgetButton memory={note} onClick={() => setConfirming(true)} />}
                </span>
            )}
            {confirming && (
                <ForgetChallenge memory={note} onSaid={onSaid} onCancel={() => setConfirming(false)}>
                    canopy deletes this note&apos;s text, and its ticket&apos;s later runs no longer read it. Its row
                    stays, saying which run wrote it. This cannot be undone. A lesson promoted from it keeps its own
                    words.
                </ForgetChallenge>
            )}
        </RowLine>
    )
}

/**
 * A lesson's verbs, under its row, shown at rest only while it is due or wrong: Renew; Edit, which opens the form for
 * its new version; and Forget, which cannot be undone and so asks for the lesson's ref typed. Until then Forget is the
 * quieter, at the line's end. With `edit` and `forget` false, as on a `lesson_review` item, Renew alone.
 */
export function LessonActions({
    lesson,
    edit = true,
    forget = true,
    onSaid,
}: Said & { lesson: MemoryEntry; edit?: boolean; forget?: boolean }) {
    const client = useQueryClient()
    const now = useNow()
    // Renewing is the decision a due or wrong lesson asks for; on one in force and not due it is there, but quiet.
    const asked = ['due', 'wrong'].includes(memoryStand(lesson, now))
    const [open, setOpen] = useState(false)
    const [confirming, setConfirming] = useState(false)
    const renew = useMutation({
        mutationFn: () => renewMemory(lesson.id),
        onSuccess: (renewed) => {
            onSaid(renewedText(renewed))
            void refreshMemory(client)
        },
        onError: (error) => void refreshIfStale(client, error, onSaid),
    })
    // A lesson that asks nothing shows its verbs only on its row's hover or focus, as a row's copy button does, so a
    // list of hundreds is not a wall of buttons, and at rest they take no room: they show over the row's end, on the
    // panel's ground, so nothing under the row moves. A touch screen, with no hover, keeps them in the row's flow.
    const shown = asked || open || confirming || renew.error !== null
    return (
        <RowLine
            from="key"
            className={cn(
                'flex flex-col gap-2',
                !shown && [
                    'pointer-fine:absolute pointer-fine:right-3 pointer-fine:bottom-1.5 pointer-fine:bg-surface',
                    'pointer-fine:pl-2 opacity-0 group-hover/copy:opacity-100 focus-within:opacity-100',
                    'pointer-coarse:opacity-100',
                    // While the row's versions are open they are its end: the verbs keep to the row's flow above them.
                    'pointer-fine:group-data-[state=open]/copy:static',
                ],
            )}
        >
            {open ? (
                <EditForm lesson={lesson} onSaid={onSaid} onClose={() => setOpen(false)} />
            ) : (
                <span className="flex flex-wrap items-center gap-2">
                    <Button
                        variant={asked ? 'outline' : 'ghost'}
                        size="xs"
                        className={cn(!asked && 'text-muted-foreground')}
                        title={`canopy memory renew ${lesson.id}`}
                        onClick={() => renew.mutate()}
                        disabled={renew.isPending}
                    >
                        <RefreshCw />
                        Renew
                    </Button>
                    {edit && (
                        <Button
                            variant="ghost"
                            size="xs"
                            className="text-muted-foreground"
                            title={`canopy memory edit ${lesson.id} --text TEXT --repo REPO`}
                            onClick={() => setOpen(true)}
                            disabled={renew.isPending}
                        >
                            <Pencil />
                            Edit
                        </Button>
                    )}
                    {forget && !confirming && (
                        <ForgetButton memory={lesson} onClick={() => setConfirming(true)} disabled={renew.isPending} />
                    )}
                </span>
            )}
            {confirming && (
                <ForgetChallenge memory={lesson} onSaid={onSaid} onCancel={() => setConfirming(false)}>
                    canopy deletes this lesson&apos;s text, and no run reads it again. Its row stays, saying who
                    promoted it and when. This cannot be undone: {backText(lesson)}
                    {lesson.version > 1 && ' Its earlier versions keep their words: forget each from its versions.'}
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
        onError: (error) => void refreshIfStale(client, error, onSaid),
    })
    const fits = lessonFits(text)
    const replaced = data === undefined ? undefined : inForceUnder(data.lessons, source.key)
    const privateWords = source.private && text.trim() === own.trim()

    const sendKeys = useSendKeys()

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (fits && !promote.isPending) {
            promote.mutate()
        }
    }

    return (
        <form
            onSubmit={submit}
            aria-label={`Promote ${memoryRef(source.id)}`}
            className="flex flex-col gap-2 rounded-md border bg-surface p-3"
        >
            <LessonFields
                text={text}
                onText={setText}
                onKeyDown={sendKeys.onKeyDown}
                repo={repo}
                onRepo={setRepo}
                choices={data === undefined ? undefined : repoChoices(source, data.repos)}
            />
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
                                : <MemoryText text={replaced.text} className="text-foreground" lines />
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
                <Button type="submit" disabled={promote.isPending || !fits} aria-keyshortcuts={sendKeys.shortcut}>
                    <ArrowUpFromLine />
                    Promote {memoryRef(source.id)}
                    <SendKeycap keys={sendKeys.shortcut} />
                </Button>
                <Button type="button" variant="ghost" onClick={onClose} disabled={promote.isPending}>
                    Cancel
                </Button>
            </span>
            <Notice error={promote.error} />
        </form>
    )
}

/** The lesson in force under `key`, which promoting a memory under it replaces, as `promote` does; else undefined. */
function inForceUnder(lessons: MemoryEntry[], key: string): MemoryEntry | undefined {
    return lessons.find((m) => m.key === key)
}

/**
 * A lesson's next version (`canopy memory edit`): its words, starting as its own and held to the bound a proposal is,
 * and the repositories whose runs it is served to, its own or every one first. The version in force stays, superseded,
 * as the lesson's history, and the new one comes up for review later with any run's report that it is wrong cleared.
 * It reads the workspace's repositories when it opens (`memoryQuery`, which the memory page has already read).
 */
export function EditForm({ lesson, onSaid, onClose }: Said & { lesson: MemoryEntry; onClose: () => void }) {
    const client = useQueryClient()
    const own = lesson.text ?? ''
    const [text, setText] = useState(own)
    const [repo, setRepo] = useState(lesson.repo)
    const { data } = useQuery(memoryQuery)
    const edit = useMutation({
        mutationFn: () =>
            editMemory(lesson.id, {
                // What is unchanged goes as null, as the CLI leaves --text and --repo out: the server trims the text.
                text: text.trim() === own.trim() ? null : text,
                repo: repo === lesson.repo || repo === null ? null : repo,
                every_repo: repo === null && lesson.repo !== null,
            }),
        onSuccess: (edited) => {
            onSaid(editedText(edited))
            onClose()
            void refreshMemory(client)
        },
        onError: (error) => void refreshIfStale(client, error, onSaid),
    })
    const changed = text.trim() !== own.trim() || repo !== lesson.repo
    const fits = lessonFits(text)
    const sendKeys = useSendKeys()

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (fits && changed && !edit.isPending) {
            edit.mutate()
        }
    }

    return (
        <form
            onSubmit={submit}
            aria-label={`Edit ${memoryRef(lesson.id)}`}
            className="flex flex-col gap-2 rounded-md border bg-surface p-3"
        >
            <LessonFields
                text={text}
                onText={setText}
                onKeyDown={sendKeys.onKeyDown}
                repo={repo}
                onRepo={setRepo}
                choices={data === undefined ? undefined : editRepoChoices(lesson, data.repos)}
            />
            <p className="min-h-4 text-xs text-muted-foreground" data-testid="edit-keeps">
                It replaces {memoryRef(lesson.id)}, which stays in the lesson&apos;s versions with its words. The new
                version is due for review in 90 days.
            </p>
            <span className="flex flex-wrap items-center gap-2">
                <Button
                    type="submit"
                    disabled={edit.isPending || !fits || !changed}
                    aria-keyshortcuts={sendKeys.shortcut}
                >
                    <Pencil />
                    Edit {memoryRef(lesson.id)}
                    <SendKeycap keys={sendKeys.shortcut} />
                </Button>
                <Button type="button" variant="ghost" onClick={onClose} disabled={edit.isPending}>
                    Cancel
                </Button>
            </span>
            <Notice error={edit.error} />
        </form>
    )
}

/**
 * Forget under one of a memory's versions out of force (`MemoryRows`' `versionVerbs`): its words leave the journal
 * while the version in force keeps its own, as `canopy memory forget ID` does for any version. A leaked secret an edit
 * took out of a lesson is still in the version before it.
 */
export function VersionForget({ version, onSaid }: Said & { version: MemoryEntry }) {
    const [confirming, setConfirming] = useState(false)
    if (!confirming) {
        return (
            <span className="flex">
                <ForgetButton memory={version} onClick={() => setConfirming(true)} />
            </span>
        )
    }
    return (
        <ForgetChallenge memory={version} onSaid={onSaid} onCancel={() => setConfirming(false)}>
            canopy deletes this version&apos;s text. Its row stays in the versions, saying when it was written, and the
            version in force keeps its own words. This cannot be undone.
        </ForgetChallenge>
    )
}

/**
 * A lesson's words and the repositories its runs are served in, as a promote or an edit takes them: the words in a
 * field with their count against the bound, sent on the send key (`onKeyDown`), and, once `choices` are read, the
 * repository to serve it in, as a picker (`RepoSelect`), which a workspace of many repositories keeps in reach.
 */
function LessonFields({
    text,
    onText,
    onKeyDown,
    repo,
    onRepo,
    choices,
}: {
    text: string
    onText: (text: string) => void
    onKeyDown: SendKeys['onKeyDown']
    repo: string | null
    onRepo: (repo: string | null) => void
    choices: (string | null)[] | undefined
}) {
    const id = useId()
    const chars = lessonChars(text)
    return (
        <>
            <span className="flex items-baseline justify-between gap-3">
                <label className="panel-label" htmlFor={`${id}-text`}>
                    The lesson, in your words
                </label>
                <span
                    className={cn(
                        'readout text-xs text-muted-foreground',
                        !lessonFits(text) && chars > 0 && 'text-status-failed',
                    )}
                    data-testid="lesson-chars"
                >
                    {chars} of {MAX_LESSON_CHARS}
                </span>
            </span>
            <Textarea
                id={`${id}-text`}
                value={text}
                onChange={(event) => onText(event.target.value)}
                onKeyDown={onKeyDown}
                spellCheck
                className="min-h-20"
            />
            {choices !== undefined && (
                <span className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-muted-foreground" aria-hidden>
                        Served to runs in
                    </span>
                    <RepoSelect choices={choices} value={repo} onValue={onRepo} label="Served to runs in" />
                </span>
            )}
        </>
    )
}

/** Whether a lesson's words fit the bound, past the spaces at either end the server trims, and are not blank. */
function lessonFits(text: string): boolean {
    const chars = lessonChars(text)
    return chars > 0 && chars <= MAX_LESSON_CHARS
}

/**
 * How a forgotten lesson could come back, as the server allows it: a note is promoted again while it keeps its text,
 * but a proposal is used up once promoted (`not_pending`), so a lesson from one cannot.
 */
function backText(lesson: MemoryEntry): string {
    if (lesson.origin?.scope === 'ticket') {
        return `promote its note, ${memoryRef(lesson.origin.id)}, again to have it back, while the note keeps its text.`
    }
    return 'it cannot come back, though a worker may propose it again.'
}

/**
 * After a verb the server refused because the memory changed under it (decided from the attention list or the CLI,
 * forgotten, or gone), read memory again, so its row leaves or shows where it stands now. Its row may leave with the
 * refusal under it, so the refusal is said under the list too.
 */
function refreshIfStale(client: QueryClient, error: Error, onSaid: (said: string) => void): Promise<void> {
    if (!(error instanceof ApiError) || !STALE.has(error.guard ?? '')) {
        return Promise.resolve()
    }
    onSaid(`refused (${error.guard ?? ''}): ${error.message}`)
    return refreshMemory(client)
}

/**
 * The quiet Forget at the end of a memory's line of verbs, which opens the challenge under it: muted at rest, since it
 * is the rarest verb and cannot be undone, and in `status-failed` only while its row is hovered or it has the focus.
 */
function ForgetButton({ memory, onClick, disabled }: { memory: MemoryEntry; onClick: () => void; disabled?: boolean }) {
    return (
        <Button
            variant="ghost"
            size="xs"
            className={cn(
                'ml-auto text-muted-foreground',
                'group-hover/copy:text-status-failed hover:text-status-failed focus-visible:text-status-failed',
            )}
            title={`canopy memory forget ${memory.id}`}
            onClick={onClick}
            disabled={disabled}
        >
            <Eraser />
            Forget
        </Button>
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
    const ref = memoryRef(memory.id)
    const forget = useMutation({
        mutationFn: (typed: string) => forgetMemory(memory.id, typed),
        onSuccess: (forgot) => {
            onSaid(memoryForgottenText(forgot))
            void refreshMemory(client)
        },
        onError: (error) => void refreshIfStale(client, error, onSaid),
    })
    return (
        <ForgetForm
            confirm={ref}
            name={`Forget ${ref}`}
            pending={forget.isPending}
            onForget={(typed) => forget.mutate(typed)}
            onCancel={onCancel}
            after={<Notice error={forget.error} />}
        >
            {children}
        </ForgetForm>
    )
}
