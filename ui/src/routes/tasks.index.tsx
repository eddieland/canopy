import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { tasksQuery } from '@/api/queries'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { RepoFilter } from '@/components/repo-picker'
import { TaskRow } from '@/components/task-row'
import { TaskSubmitForm } from '@/components/task-submit'
import { countText, reposOf } from '@/lib/pull-request-filter'
import { repoListFrom, repoListOf, reposIn, reposWords } from '@/lib/repo-filter'
import { tasksShown } from '@/lib/tasks'

interface TasksSearch {
    repo?: string | undefined
}

/**
 * Every task the operator submitted, the ones waiting on their reply first, then the newest first, under the form that
 * submits one. `?repo=` keeps the tasks in its repositories, and starts the form at the one it names.
 */
export const Route = createFileRoute('/tasks/')({
    // Typed search params, as the pull requests page's: every key returned, undefined when the page does not offer it.
    validateSearch: (search: Record<string, unknown>): TasksSearch => ({
        repo: repoListOf(search['repo']),
    }),
    component: TasksPage,
})

function TasksPage() {
    const { repo } = Route.useSearch()
    const query = useQuery(tasksQuery)
    const { data } = query
    const shown = data === undefined ? undefined : tasksShown(data, repo)
    return (
        <>
            <PageHeader title="Tasks">
                One-off work you handed canopy in your own words, about no ticket: a question to explore, an approach to
                try, the tickets to plan. A worker runs each once in a worktree of its repository and leaves a report, a
                branch, and perhaps a draft PR or some tickets. Those waiting on your reply come first.
            </PageHeader>
            <Panel>
                <PanelHeader label="Submit a task" />
                <TaskSubmitForm tasks={data} filter={repo} />
            </Panel>
            <Panel>
                <PanelHeader label="Tasks">
                    <span className="readout text-xs text-muted-foreground" data-testid="tasks-count">
                        {countText(shown?.length, data?.length, repo !== undefined)}
                    </span>
                </PanelHeader>
                {data !== undefined && <Filter repos={reposOf(data, repo)} />}
                {data === undefined || shown === undefined ? (
                    <PanelLoading query={query} className="min-h-72" />
                ) : data.length === 0 ? (
                    <Empty size="panel">no tasks yet: one you submit above starts at the next tick</Empty>
                ) : shown.length === 0 ? (
                    <Empty size="panel">{`no tasks in ${reposWords(repo ?? '')}`}</Empty>
                ) : (
                    <ul className="divide-y" data-testid="tasks">
                        {shown.map((task) => (
                            <TaskRow key={task.id} task={task} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

/** The repository picker, kept in `?repo=`, while the tasks are in more than one repository (`RepoFilter`). */
function Filter({ repos }: { repos: string[] }) {
    const { repo } = Route.useSearch()
    const navigate = Route.useNavigate()
    if (repos.length < 2) {
        return null
    }
    return (
        <search className="flex items-center border-b px-3 py-2">
            <RepoFilter
                repos={repos}
                chosen={reposIn(repo)}
                onChoose={(chosen) => void navigate({ search: { repo: repoListFrom(chosen) }, replace: true })}
            />
        </search>
    )
}
