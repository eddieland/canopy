import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Waypoints } from 'lucide-react'
import { useState } from 'react'
import type { SubmitEvent } from 'react'

import { newSubmission, submitEpic } from '@/api/mutations'
import { keys, metaQuery } from '@/api/queries'
import { Input } from '@/components/input'
import { MarkdownField } from '@/components/markdown-field'
import { Notice } from '@/components/notice'
import { ReposChoice } from '@/components/repo-picker'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { epicSubmittedToast } from '@/lib/outcomes'
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
 * replaces, naming its guard. Its submission id is drawn when the form is rendered and kept until an epic is
 * recorded, so sending again after an uncertain result files no second epic (DESIGN §43). Once it is recorded, a toast
 * says what the CLI says and the form opens the epic's page, which says its plan run is to come; the list is read
 * again at once, rather than wait for the stream's `epics.updated`.
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
    // Drawn anew once an epic is recorded, so a retry of the same one records nothing new.
    const [submission, setSubmission] = useState(newSubmission)
    // A workspace of one needs no name: the server reads its one repository, as the CLI does.
    const several = repos.length > 1
    const named = chosen.filter((repo) => repos.includes(repo))
    const mutation = useMutation({
        mutationFn: () => submitEpic(text, several ? named : [], optional(project), optional(trackerEpic), submission),
        onSuccess: (submitted) => {
            setSubmission(newSubmission())
            toast(epicSubmittedToast(submitted))
            void client.invalidateQueries({ queryKey: keys.epics })
            void navigate({ to: '/epics/$id', params: { id: String(submitted.id) } })
        },
    })
    const unnamed = several && named.length === 0
    // Until the workspace's repositories are read, a workspace of several would be refused for naming none.
    const ready = meta !== undefined && text.trim() !== '' && !unnamed && !mutation.isPending

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (ready) {
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
            <Notice error={mutation.error}>
                {several && 'Its plan reads only the repositories you name. '}
                With no project it files no tickets. A tracker epic&apos;s tickets are only suggestions: none is a
                member until you add it.
            </Notice>
        </form>
    )
}

// What an optional key's field sends: the key as typed, trimmed, or null for none.
function optional(value: string): string | null {
    const trimmed = value.trim()
    return trimmed === '' ? null : trimmed
}
