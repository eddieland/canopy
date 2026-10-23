import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Sprout } from 'lucide-react'
import { useState } from 'react'
import type { SubmitEvent } from 'react'

import { submitTask } from '@/api/mutations'
import { metaQuery } from '@/api/queries'
import type { TaskSummary } from '@/api/types'
import { Input, Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { RepoSelect } from '@/components/repo-picker'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { taskSubmittedToast } from '@/lib/outcomes'
import { useSendKeys } from '@/lib/send-key'
import { submitRepo } from '@/lib/tasks'

// The operator's bound (DESIGN §36): the server refuses more, after stripping, rather than cut it.
const MAX_TEXT = 4000

/**
 * `canopy task submit TEXT --repo NAME --project KEY` from the tasks page (DESIGN §36), as compact as a ticket's
 * `StartTicket`: the text in a field one line high that grows as it is written, the repository it runs in while the
 * workspace has several (`RepoSelect`, starting at `submitRepo`'s), the tracker project its tickets may go in, and an
 * outline `Submit`, which the send key presses too. Under them one line says what a task may do, which a refusal
 * replaces, naming its guard. Once it is recorded, a toast says what the CLI says and the form opens the task's page;
 * the list hears of the task from the stream, as of one submitted from the shell.
 */
export function TaskSubmitForm({ tasks, filter }: { tasks: readonly TaskSummary[] | undefined; filter?: string }) {
    const navigate = useNavigate()
    const toast = useToast()
    const sendKeys = useSendKeys()
    const { data: meta } = useQuery(metaQuery)
    const repos = meta?.repos ?? []
    const [text, setText] = useState('')
    const [project, setProject] = useState('')
    // The repository picked for this task, or null for the one it starts at.
    const [picked, setPicked] = useState<string | null>(null)
    const repo = picked ?? submitRepo(repos, filter, tasks)
    const mutation = useMutation({
        mutationFn: () => submitTask(text, repo, project.trim() === '' ? null : project.trim()),
        onSuccess: (submitted) => {
            toast(taskSubmittedToast(submitted))
            void navigate({ to: '/tasks/$id', params: { id: String(submitted.id) } })
        },
    })
    // Until the workspace's repositories are read, a workspace of several would be refused for naming none.
    const ready = meta !== undefined && text.trim() !== '' && !mutation.isPending

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (ready) {
            mutation.mutate()
        }
    }

    return (
        <form onSubmit={submit} aria-label="Submit a task" className="flex flex-col gap-2 p-3">
            <div className="flex flex-wrap items-start gap-2">
                <Textarea
                    aria-label="Task"
                    rows={1}
                    value={text}
                    maxLength={MAX_TEXT}
                    onChange={(event) => setText(event.target.value)}
                    onKeyDown={sendKeys.onKeyDown}
                    placeholder="What to find out, try, or plan"
                    // One line high, as the field beside it is, until it holds more: it grows to 15rem, then scrolls.
                    className="field-sizing-content max-h-60 min-h-9 min-w-64 flex-1 resize-none py-1.75 leading-5"
                />
                {repos.length > 1 && repo !== null && (
                    <span className="flex h-9 items-center">
                        <RepoSelect choices={repos} value={repo} onValue={setPicked} label="Runs in" />
                    </span>
                )}
                <Input
                    aria-label="Tracker project"
                    title="canopy task submit TEXT --project KEY"
                    placeholder="project, optional"
                    value={project}
                    onChange={(event) => setProject(event.target.value)}
                    className="w-40 font-mono text-xs"
                />
                <Button
                    type="submit"
                    variant="outline"
                    disabled={!ready}
                    title="canopy task submit TEXT"
                    aria-keyshortcuts={sendKeys.shortcut}
                >
                    <Sprout />
                    Submit
                    <SendKeycap keys={sendKeys.shortcut} />
                </Button>
            </div>
            <Notice error={mutation.error}>
                It opens a draft PR only if your text asks for one, and files tickets only in the project you name, none
                without one.
            </Notice>
        </form>
    )
}
