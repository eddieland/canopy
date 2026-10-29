import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { RotateCw } from 'lucide-react'
import { useState } from 'react'

import { skillsQuery } from '@/api/queries'
import type { Skill, SkillList } from '@/api/types'
import { CopyButton } from '@/components/copy-button'
import { Disclosure } from '@/components/disclosure'
import { FilterField } from '@/components/filter-field'
import { Notice } from '@/components/notice'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { SKILL_QUERY_MAX, skillQueryOf, skillsLine, skillsMatching, SOURCE_MEANING } from '@/lib/skills'

// What the page shows, the same on every visit: the title's help, so the description is left for what was found.
const HELP =
    "Every skill the runtime finds where the loop starts canopy's agents: where its file is, and what it says. A " +
    'skill an agent is offered costs each of its model calls, loaded or not. Read from the runtime when the page ' +
    'opens, and again when you ask.'

interface SkillsSearch {
    q?: string | undefined
}

/**
 * The skills the runtime finds for canopy's agents (DESIGN §13), a page of Settings' own: each skill's name, what it
 * says it is for, where its file is, and its text, opened under it. `?q=` keeps the skills whose name or description
 * holds it. It changes nothing: a skill is added or denied in the runtime's own config.
 */
export const Route = createFileRoute('/settings_/skills')({
    validateSearch: (search: Record<string, unknown>): SkillsSearch => ({ q: skillQueryOf(search['q']) }),
    component: SkillsPage,
})

function SkillsPage() {
    const { q } = Route.useSearch()
    const navigate = Route.useNavigate()
    const query = useQuery(skillsQuery)
    const { data, error, refetch, isFetching } = query
    const shown = data === undefined ? undefined : skillsMatching(data.skills, q)
    return (
        <>
            <PageHeader title="Skills" help={HELP}>
                {described(data, query.isPending)}
            </PageHeader>
            <Panel data-testid="skills">
                <PanelHeader label="Skills">
                    <span className="flex items-center gap-3">
                        <Button
                            variant="ghost"
                            size="xs"
                            onClick={() => void refetch()}
                            disabled={isFetching}
                            title="Asks the runtime again, which starts it once"
                            data-testid="skills-refresh"
                        >
                            <RotateCw />
                            {isFetching ? 'Reading' : 'Read again'}
                        </Button>
                        <span className="readout text-xs text-muted-foreground">{shown?.length}</span>
                    </span>
                </PanelHeader>
                {data !== undefined && (data.skills.length > 0 || q !== undefined) && (
                    <search className="border-b px-3 py-2">
                        <FilterField
                            q={q}
                            queryOf={skillQueryOf}
                            onFilter={(text) => void navigate({ search: { q: text }, replace: true })}
                            label="Filter skills by name or description"
                            placeholder="Filter by name or description"
                            maxLength={SKILL_QUERY_MAX}
                        />
                    </search>
                )}
                {/* A failed read again keeps the skills on screen, under why. */}
                {data !== undefined && <Notice error={error} className="border-b px-3 py-2" />}
                {data !== undefined && data.error !== null && (
                    <Notice error={data.error} subject="runtime" className="border-b px-3 py-2" />
                )}
                {shown === undefined ? (
                    <PanelLoading query={query} rows={4} className="min-h-40" />
                ) : shown.length === 0 && q !== undefined ? (
                    <Empty>no skill&apos;s name or description holds “{q}”</Empty>
                ) : shown.length === 0 ? (
                    data?.error === null && (
                        <Empty>
                            no skills yet: add one where your runtime looks, in your home or the workspace&apos;s config
                        </Empty>
                    )
                ) : (
                    <ul className="divide-y">
                        {shown.map((skill) => (
                            <SkillRow key={skill.name} skill={skill} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

/** The page's description: what the runtime found, that it could not say, or that it is being asked. */
function described(data: SkillList | undefined, pending: boolean): string | null {
    if (data === undefined) {
        return pending ? 'asking the runtime' : null
    }
    return data.error === null ? skillsLine(data) : 'the runtime could not say'
}

/** One skill: its name and where its file is, what it says it is for, and its text, opened under it. */
function SkillRow({ skill }: { skill: Skill }) {
    const [open, setOpen] = useState(false)
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`skill-${skill.name}`}>
                <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                    <h3 className="font-mono text-sm font-medium">{skill.name}</h3>
                    <Chip word={skill.source} meaning={SOURCE_MEANING[skill.source]} />
                    {/* A built-in skill has no file to show: its chip says all its mark would. */}
                    {skill.source !== 'built-in' && (
                        <span className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
                            <span className="truncate font-mono" title={skill.path}>
                                {skill.path}
                            </span>
                            <CopyButton text={skill.path} label="path" />
                        </span>
                    )}
                </div>
                <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 text-sm">
                        {skill.description ?? <span className="text-muted-foreground">no description</span>}
                    </p>
                    <Disclosure open={open} what="SKILL.md" className="-mr-2 shrink-0" />
                </div>
                <CollapsibleContent className="-mx-3 -mb-2.5 border-t bg-surface-raised/40">
                    {skill.body.trim() === '' ? (
                        <Empty>no instructions: the file holds its front matter alone</Empty>
                    ) : (
                        <PanelScroll label={`${skill.name}'s instructions`}>
                            <RichText text={skill.body} prose className="p-3" />
                        </PanelScroll>
                    )}
                </CollapsibleContent>
            </li>
        </Collapsible>
    )
}
