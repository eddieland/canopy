import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { RotateCw } from 'lucide-react'

import { checklistsQuery } from '@/api/queries'
import type { ChecklistItem, ChecklistList, RepoChecklist } from '@/api/types'
import { Code } from '@/components/code'
import { CopyButton } from '@/components/copy-button'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { checklistsLine, itemKey, SEVERITY_MEANING } from '@/lib/checklist'
import { SEVERITY_TONE } from '@/lib/reviews'

// What the page shows on every visit, on its title's hover: its description is what the lists hold.
const HELP =
    "Each repository's checklist, as the next worker run in it would hear it: the rules a worker holds its diff to " +
    'before it pushes. Read from your paths.checklists directory when the page opens, and again when you ask. ' +
    'Nothing here changes a list: edit its file, and the next run reads it.'

/**
 * Each mapped repository's checklist (DESIGN §42), read only: its file, and its items in order, each with its id, the
 * paths it is about, its severity, and its rule, linked to how runs answered it under Reports. A repository with no
 * list says so, and one canopy cannot use says why, as its runs' refusal would. It changes nothing: a list is the
 * operator's file.
 */
export const Route = createFileRoute('/workspace/checklists')({
    component: ChecklistsPage,
})

function ChecklistsPage() {
    const query = useQuery(checklistsQuery)
    const { data, error, refetch, isFetching } = query
    return (
        <>
            <PageHeader
                title="Checklists"
                help={HELP}
                links={
                    <Link to="/reports/checklist" className="text-xs text-accent underline-offset-4 hover:underline">
                        How runs answered them
                    </Link>
                }
            >
                {data === undefined ? null : checklistsLine(data)}
            </PageHeader>
            {data === undefined ? (
                <Panel>
                    <PanelHeader label="Checklists" />
                    <PanelLoading query={query} rows={4} className="min-h-40" />
                </Panel>
            ) : (
                <>
                    <Directory list={data} reading={isFetching} onReadAgain={() => void refetch()} />
                    {/* A failed read again keeps the lists on screen, under why. */}
                    <Notice error={error} />
                    {data.directory !== null && data.repos.map((repo) => <RepoPanel key={repo.repo} repo={repo} />)}
                </>
            )}
        </>
    )
}

/** Where the lists are read from, or that no directory is set, with the button that reads them again. */
function Directory({ list, reading, onReadAgain }: { list: ChecklistList; reading: boolean; onReadAgain: () => void }) {
    return (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            {list.directory === null ? (
                <p>
                    <Code>paths.checklists</Code> is not set in your config, so no worker is asked a list. Point it at a
                    directory of <Code>&lt;repo&gt;.md</Code> files to start.
                </p>
            ) : (
                <span className="flex min-w-0 items-center gap-1">
                    <span className="shrink-0">Read from</span>
                    <span className="truncate font-mono" title={list.directory} data-testid="checklists-directory">
                        {list.directory}
                    </span>
                    <CopyButton text={list.directory} label="directory" />
                </span>
            )}
            <Button
                variant="ghost"
                size="xs"
                onClick={onReadAgain}
                disabled={reading}
                title="Reads the files again"
                data-testid="checklists-refresh"
            >
                <RotateCw />
                {reading ? 'Reading' : 'Read again'}
            </Button>
        </div>
    )
}

/** One repository's list: its items in order, that it has none, or why canopy cannot use its file. */
function RepoPanel({ repo }: { repo: RepoChecklist }) {
    const name = repo.file?.split('/').at(-1) ?? `${repo.repo}.md`
    return (
        <Panel data-testid={`checklist-${repo.repo}`}>
            <PanelHeader label={repo.repo}>
                <span className="flex items-center gap-2">
                    <span className="font-mono text-xs text-muted-foreground" title={repo.file ?? undefined}>
                        {name}
                    </span>
                    <span className="readout text-xs text-muted-foreground">
                        {repo.error === null ? repo.items.length : ''}
                    </span>
                </span>
            </PanelHeader>
            {/* A file canopy cannot use refuses each of the repository's runs that would hear it, so it says why. */}
            {repo.error === null ? (
                repo.items.length === 0 ? (
                    <Empty>
                        no list: its workers are asked nothing until <Code>{name}</Code> is in the directory
                    </Empty>
                ) : (
                    <ol className="divide-y">
                        {repo.items.map((item) => (
                            <ItemRow key={item.id} repo={repo.repo} item={item} />
                        ))}
                    </ol>
                )
            ) : (
                <Notice error={repo.error} subject="runs refused (bad_prompt)" className="px-3 py-2.5" />
            )}
        </Panel>
    )
}

/** One item: its id, severity, and paths on a line, its rule under them, and a link to how runs answered it. */
function ItemRow({ repo, item }: { repo: string; item: ChecklistItem }) {
    return (
        <li className="flex flex-col gap-1.5 px-3 py-2.5" data-testid={`checklist-item-${item.id}`}>
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <h3 className="font-mono text-sm font-medium">{item.id}</h3>
                <Chip
                    tone={SEVERITY_TONE[item.severity]}
                    word={item.severity}
                    meaning={SEVERITY_MEANING[item.severity]}
                />
                <span className="flex min-w-0 flex-wrap items-center gap-1 text-xs text-muted-foreground">
                    {item.paths.length === 0 ? 'every path' : item.paths.map((p) => <Code key={p}>{p}</Code>)}
                </span>
                <Link
                    to="/reports/checklist"
                    search={{ repo, item: itemKey({ repo, item: item.id }) }}
                    className="ml-auto text-xs text-accent underline-offset-4 hover:underline"
                >
                    Answers
                </Link>
            </div>
            <RichText text={item.rule} prose className="text-sm" />
        </li>
    )
}
