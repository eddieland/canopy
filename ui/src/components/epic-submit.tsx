import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Paperclip, Waypoints, X } from 'lucide-react'
import { useRef, useState } from 'react'
import type { SubmitEvent } from 'react'

import { attachFile, submitEpic } from '@/api/mutations'
import { keys, metaQuery } from '@/api/queries'
import type { Attached } from '@/api/types'
import { Input } from '@/components/input'
import { MarkdownField } from '@/components/markdown-field'
import { Notice } from '@/components/notice'
import { ReposChoice } from '@/components/repo-picker'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { ATTACHMENT_TYPES, readBeside, sizeText } from '@/lib/attachments'
import type { HeldFile } from '@/lib/attachments'
import { epicSubmittedToast } from '@/lib/outcomes'
import type { Missed } from '@/lib/outcomes'
import { useSendKeys } from '@/lib/send-key'

// The operator's bound (DESIGN §43): the server refuses more, after stripping, rather than cut it.
const MAX_TEXT = 4000

/**
 * `canopy epic submit TEXT --repo NAME --project KEY --tracker-epic KEY` from the epics page (DESIGN §43), as the tasks
 * page's `TaskSubmitForm` submits a task: the goal in a `MarkdownField` with its toolbar, so it is dictated where the
 * server offers dictation, since a goal runs to a paragraph or two; then, on a line under it, the repositories its plan
 * reads while the workspace has several (`ReposChoice`, none chosen until the operator names them, as the CLI asks),
 * the tracker project its tickets are filed in, the tracker epic whose tickets are put to them as suggestions, and an
 * outline `Submit`, which the send key presses too. Under them one line says what the optional two do, which a refusal
 * replaces, naming its guard. Once it is recorded, a toast says what the CLI says and the form opens the epic's page,
 * which says its plan run is to come; the list is read again, since no stream event carries an epic.
 *
 * Attach a file holds text files for the epic, listed under the goal, each with a button that drops it: each is read
 * and checked as it is chosen, against the limits the server's meta says, as `canopy attach` would refuse it, so a
 * file the epic could not take is refused before anything is recorded. Once the epic is, each is attached in turn, as
 * `canopy attach epic:N FILE` does, before the next tick starts the plan run that reads them. One the server refuses
 * still, as under a limit lowered since, fails the toast, which names it and says to attach it on the epic's page.
 */
export function EpicSubmitForm() {
    const navigate = useNavigate()
    const toast = useToast()
    const client = useQueryClient()
    const sendKeys = useSendKeys()
    const { data: meta } = useQuery(metaQuery)
    const repos = meta?.repos ?? []
    const [text, setText] = useState('')
    const [chosen, setChosen] = useState<string[]>([])
    const [project, setProject] = useState('')
    const [trackerEpic, setTrackerEpic] = useState('')
    const [files, setFiles] = useState<HeldFile[]>([])
    const [fileError, setFileError] = useState<unknown>(null)
    const picker = useRef<HTMLInputElement>(null)
    const limits = meta?.attachment_limits
    // A workspace of one needs no name: the server reads its one repository, as the CLI does.
    const several = repos.length > 1
    const named = chosen.filter((repo) => repos.includes(repo))
    const mutation = useMutation({
        mutationFn: async () => {
            const submitted = await submitEpic(text, several ? named : [], optional(project), optional(trackerEpic))
            const attached: Attached[] = []
            const missed: Missed[] = []
            for (const file of files) {
                try {
                    // oxlint-disable-next-line eslint/no-await-in-loop -- one after another, in the order listed
                    attached.push(await attachFile({ kind: 'epic', id: submitted.id }, file.name, file.text))
                } catch (error) {
                    missed.push({ name: file.name, error })
                }
            }
            return { submitted, attached, missed }
        },
        onSuccess: ({ submitted, attached, missed }) => {
            toast(epicSubmittedToast(submitted, attached, missed))
            void client.invalidateQueries({ queryKey: keys.epics })
            void navigate({ to: '/epics/$id', params: { id: String(submitted.id) } })
        },
    })
    const unnamed = several && named.length === 0
    // Until the workspace's repositories are read, a workspace of several would be refused for naming none.
    const ready = meta !== undefined && text.trim() !== '' && !unnamed && !mutation.isPending

    async function hold(picked: readonly File[]) {
        setFileError(null)
        const held = [...files]
        for (const file of picked) {
            try {
                // oxlint-disable-next-line eslint/no-await-in-loop -- each is checked beside the ones before it
                held.push(await readBeside(file, held, limits ?? NO_LIMITS, 'the epic'))
            } catch (error) {
                setFileError(error)
                break
            }
        }
        setFiles(held)
    }

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (ready) {
            setFileError(null)
            mutation.mutate()
        }
    }

    return (
        <form onSubmit={submit} aria-label="Submit an epic" className="flex flex-col gap-2 p-3">
            <MarkdownField
                aria-label="Goal"
                value={text}
                maxLength={MAX_TEXT}
                onValueChange={setText}
                onKeyDown={sendKeys.onKeyDown}
                placeholder="The goal, in your own words: what is true once it is done, and why"
                className="focus-within:bg-accent/8"
            />
            {files.length > 0 && (
                <ul aria-label="Files to attach" className="flex flex-col gap-1">
                    {files.map((file) => (
                        <li key={file.name} className="flex items-center gap-2 font-mono text-xs">
                            <span className="min-w-0 truncate" title={file.name}>
                                {file.name}
                            </span>
                            <span className="shrink-0 text-muted-foreground">{sizeText(file.size)}</span>
                            <Button
                                variant="ghost"
                                size="icon-xs"
                                className="ml-auto"
                                aria-label={`Drop ${file.name}`}
                                disabled={mutation.isPending}
                                onClick={() => {
                                    setFileError(null)
                                    setFiles(files.filter((f) => f !== file))
                                }}
                            >
                                <X />
                            </Button>
                        </li>
                    ))}
                </ul>
            )}
            <div className="flex flex-wrap items-center gap-2">
                {several && (
                    <ReposChoice
                        repos={repos}
                        chosen={named}
                        onChoose={setChosen}
                        label="Its plan reads"
                        none="repositories it reads"
                    />
                )}
                <Input
                    aria-label="Tracker project"
                    title="canopy epic submit TEXT --project KEY"
                    placeholder="project, optional"
                    value={project}
                    onChange={(event) => setProject(event.target.value)}
                    className="w-40 font-mono text-xs"
                />
                <Input
                    aria-label="Tracker epic"
                    title="canopy epic submit TEXT --tracker-epic KEY"
                    placeholder="tracker epic, optional"
                    value={trackerEpic}
                    onChange={(event) => setTrackerEpic(event.target.value)}
                    className="w-44 font-mono text-xs"
                />
                {limits !== undefined && limits.max_files > 0 && (
                    <>
                        <Button
                            variant="outline"
                            disabled={mutation.isPending || files.length >= limits.max_files}
                            title={`canopy attach epic:N FILE, once it is recorded: at most ${limits.max_files} files`}
                            onClick={() => picker.current?.click()}
                        >
                            <Paperclip />
                            Attach a file
                        </Button>
                        <input
                            ref={picker}
                            type="file"
                            multiple
                            className="sr-only"
                            tabIndex={-1}
                            aria-label="Files to attach to the epic"
                            accept={ATTACHMENT_TYPES}
                            onChange={(event) => {
                                const picked = [...(event.currentTarget.files ?? [])]
                                // Cleared, so choosing the same file again, once dropped, holds it again.
                                event.currentTarget.value = ''
                                void hold(picked)
                            }}
                        />
                    </>
                )}
                <Button
                    type="submit"
                    variant="outline"
                    disabled={!ready}
                    title={unnamed ? 'Name each repository its plan reads first' : 'canopy epic submit TEXT'}
                    aria-keyshortcuts={sendKeys.shortcut}
                    className="ml-auto"
                >
                    <Waypoints />
                    Submit
                    <SendKeycap keys={sendKeys.shortcut} />
                </Button>
            </div>
            <Notice error={mutation.error ?? fileError}>
                {several && 'Its plan reads only the repositories you name. '}
                With no project it files no tickets. A tracker epic&apos;s tickets are only suggestions: none is a
                member until you add it.
            </Notice>
        </form>
    )
}

// Never read: the button that chooses files shows only once the meta, and its limits, are read.
const NO_LIMITS = { max_files: 0, max_file_bytes: 0, max_total_bytes: 0 }

// What an optional key's field sends: the key as typed, trimmed, or null for none.
function optional(value: string): string | null {
    const trimmed = value.trim()
    return trimmed === '' ? null : trimmed
}
