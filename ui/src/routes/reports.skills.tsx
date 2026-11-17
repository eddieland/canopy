import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { skillsReportQuery } from '@/api/queries'
import type { SkillsAgent, SkillsReport } from '@/api/types'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelSkeleton } from '@/components/panel'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { Clipped } from '@/components/tip'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { WindowToggle } from '@/components/window-toggle'
import { barPercent } from '@/lib/chart'
import { readoutDelta, wholeChange } from '@/lib/readout-delta'
import { windowBefore, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import {
    agentCallTip,
    agentLoadsTip,
    coverageText,
    DEFAULT_SKILLS_WINDOW,
    frontMatterTip,
    loadsTip,
    noOffer,
    noOfferTip,
    offersText,
    pickedAgent,
    rateText,
    rateTip,
    SKILLS_SORTS,
    SKILLS_WINDOWS,
    skillRows,
    skillsAgent,
    skillsFigures,
    skillsLine,
    skillsSort,
    skillsWindow,
    sortedAgents,
    sortedRows,
    tokensChange,
} from '@/lib/skill-report'
import type { SkillRow, SkillsSort } from '@/lib/skill-report'
import { tokenCount } from '@/lib/transcript'
import { cn } from '@/lib/utils'

interface SkillsSearch {
    days?: number | undefined
    order?: SkillsSort | undefined
    agent?: string | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP =
    'Which skills the agents were offered and which they loaded, over the last days. A skill an agent is offered ' +
    'rides in each of its model calls by its front matter, its name and description, loaded or not; one it loads ' +
    "puts its text into the run's context besides. Each agent, by what its whole list adds to a model call: pick " +
    'one for its own skills. Then each skill, by what its front matter came to and how often a run offered it ' +
    'loaded it. Every count of tokens is an estimate, characters over 4, and a short window cannot tell a skill ' +
    'nobody needs from one whose work did not come up. The page changes no skill: one is denied to an agent, by ' +
    "name, in the runtime's own config."

// What a column or a tile counts, in its name's tip.
const EST = 'characters over 4, an estimate'
const CARRIED = "An estimate, and most are read from the model's cache: context carried, not a price"
const OFFERED_TILE_HINT = 'The skills a run was offered, by name: each rides in every model call of a run offered it'
const UNUSED_TILE_HINT = 'Of those, the skills no run of any agent loaded, in a run offered them or any other'
const CALL_TILE_HINT =
    "About how many tokens the skills' front matter adds to one model call of a run offered a skill, the mean of " +
    `the calls counted: ${EST}`
const SENT_TILE_HINT = `About how many tokens the skills' front matter added to the counted runs' calls. ${CARRIED}`
const RUNS_HINT = 'Its runs that started in the window and have ended'
const NO_OFFER_HINT =
    'Of those, the runs nothing says what they were offered: canopy never asked about them, or the runtime could ' +
    'not answer. They count under the agent canopy ships for their kind of run'
const AGENT_SKILLS_HINT = 'How many skills its runs were offered, by name'
const AGENT_UNUSED_HINT = 'Of those, the skills none of its runs loaded'
const AGENT_CALL_HINT =
    'About how many tokens the front matter of every skill offered adds to one of its model calls, the mean of ' +
    `the calls counted: ${EST}`
const AGENT_SENT_HINT = `About how many tokens that added to the counted runs' model calls, all told. ${CARRIED}`
const AGENT_LOADS_HINT = 'Its calls of the skill tool that did not fail, of every skill canopy could name'
const OFFERED_HINT = 'The runs the runtime said it offered the skill: it rides in each of their model calls'
const RATE_HINT =
    'The runs that loaded it, as a share of the runs offered it. A skill a prompt says to load first, as the ' +
    "tracker's is, is loaded by most runs: that is the prompt at work"
const CALL_HINT =
    'About how many tokens its front matter, its name and description, adds to each model call of a run offered ' +
    `it, at its newest offer on record: ${EST}`
const SENT_HINT =
    'About how many tokens its front matter added to the model calls of the runs counted, its length at each run ' +
    `for each of the run's model calls. ${CARRIED}`
const LOADS_HINT = 'The calls of the skill tool for it that did not fail, in every run, offered it on record or not'
const FAILED_HINT = 'The calls for it that failed, as one for a skill the agent is denied does: the deny at work'
const BODY_HINT =
    "About how many tokens its loads put into the runs' context, its text, which each later model call of the run " +
    `reads again: ${EST}`

// A figure the journal cannot say, and why, on its tip.
const UNSIZED = "no offer in this window recorded its description's length"
const UNNAMED = 'its loads are among those that named no skill'

/**
 * Which skills the agent runs of the last days were offered and loaded, and what each one's front matter cost: each
 * agent, then each skill, over every agent or the one picked. The window is `?days=`, the week or 30 days, the
 * skills' order `?order=`, and the agent picked `?agent=`; the week, by front matter, over every agent, the
 * defaults, need no search.
 */
export const Route = createFileRoute('/reports/skills')({
    // Typed search params: a window or an order the page does not offer is dropped, which reads as its default. Any
    // agent's name is kept: the page holds it to the agents the window has.
    validateSearch: (search: Record<string, unknown>): SkillsSearch => ({
        days: skillsWindow(search)?.days,
        order: skillsSort(search),
        agent: skillsAgent(search),
    }),
    component: SkillsPage,
})

function SkillsPage() {
    const search = Route.useSearch()
    const shown: ReportWindow = search.days === undefined ? DEFAULT_SKILLS_WINDOW : { days: search.days }
    const navigate = Route.useNavigate()
    const query = useQuery(skillsReportQuery(shown.days ?? 7))
    const span = windowName(shown)
    const { data } = query
    // A read that failed with nothing on screen says so once, in the first panel, with Read again.
    const failed = data === undefined && query.error !== null
    const picked = pickedAgent(data?.agents ?? [], search.agent)
    const rows = data === undefined ? [] : sortedRows(skillRows(data.skills, picked?.agent), search.order)
    return (
        <>
            <PageHeader
                title="Skills"
                help={HELP}
                controls={
                    <WindowToggle
                        windows={SKILLS_WINDOWS}
                        shown={shown}
                        testId="skills"
                        onPick={(window) => {
                            void navigate({
                                search: (prev) => ({
                                    ...prev,
                                    days: window === DEFAULT_SKILLS_WINDOW ? undefined : window.days,
                                }),
                            })
                        }}
                    />
                }
                links={
                    !failed && <ReadoutTiles tiles={skillsTiles(data)} against={windowBefore(shown)} testId="skills" />
                }
            >
                {data === undefined
                    ? query.isPending
                        ? 'reading what the runs were offered'
                        : null
                    : skillsLine(data)}
            </PageHeader>
            <Panel data-testid="skills-agents">
                <PanelHeader label="Agents">
                    <span className="readout text-xs text-muted-foreground">{data?.agents.length ?? ''}</span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelLoading query={query} rows={4} className="min-h-40" />
                ) : (
                    <Agents found={data} span={span} />
                )}
            </Panel>
            {!failed && (
                <Panel data-testid="skills-skills">
                    <PanelHeader label="Skills">
                        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <SortToggle />
                            <Scope picked={picked} />
                            <span className="readout text-xs text-muted-foreground" data-testid="skills-count">
                                {data === undefined ? '' : countText(rows.length, data.skills.length)}
                            </span>
                        </span>
                    </PanelHeader>
                    {data === undefined ? (
                        <PanelSkeleton rows={8} className="min-h-64" />
                    ) : (
                        <Skills found={data} rows={rows} picked={picked} span={span} />
                    )}
                </Panel>
            )}
        </>
    )
}

/**
 * The window's headline figures, each held in its place while the report is read. The counts are set against the
 * window before's, and so is the front matter of a call, a mean, where both windows have one; its sum is not, since
 * it grows with the runs counted. None is colored: more skills, or a longer list, is not a thing broken. The two of
 * front matter are left out while no run is counted for one, rather than show a dash for a figure.
 */
function skillsTiles(found: SkillsReport | undefined): ReadoutTile[] {
    const figures = found === undefined ? undefined : skillsFigures(found)
    const before = found === undefined ? undefined : skillsFigures(found.previous)
    const counts: ReadoutTile[] = [
        {
            key: 'offered',
            label: 'skills offered',
            hint: OFFERED_TILE_HINT,
            value: figures?.offered,
            delta: readoutDelta(figures?.offered, before?.offered, wholeChange),
        },
        {
            key: 'unused',
            label: 'never loaded',
            hint: UNUSED_TILE_HINT,
            value: figures?.unused,
            delta: readoutDelta(figures?.unused, before?.unused, wholeChange),
        },
    ]
    if (found?.est_front_matter_tokens === null) {
        return counts
    }
    return [
        ...counts,
        {
            key: 'call',
            label: '~tokens a call',
            hint: CALL_TILE_HINT,
            value: found === undefined ? undefined : tokenCount(found.est_call_tokens ?? 0),
            delta: readoutDelta(figures?.call, before?.call, tokensChange),
        },
        {
            key: 'sent',
            label: 'front matter ~tokens',
            hint: SENT_TILE_HINT,
            value: found === undefined ? undefined : tokenCount(found.est_front_matter_tokens),
        },
    ]
}

// The skills table's count: how many it lists, and of how many once an agent narrows it: `7 of 9`.
function countText(listed: number, all: number): string {
    return listed === all ? String(all) : `${listed} of ${all}`
}

/**
 * Each agent that ran, the heaviest list a call first: its runs, those with no offer on record, the skills it was
 * offered and how many of those none of its runs loaded, what their front matter adds to one of its model calls,
 * with a bar of the most's, and what that came to. An agent's name picks it for the skills table under it. Under the
 * table, the runs nothing says what they were offered, split by why.
 */
function Agents({ found, span }: { found: SkillsReport; span: string }) {
    if (found.agents.length === 0) {
        return <Empty size="panel">no agent ran in these {span}</Empty>
    }
    const agents = sortedAgents(found.agents)
    return (
        <div className="flex flex-col gap-3 pb-3">
            <ReportTable
                rows={agents}
                columns={agentColumns(agents)}
                rowKey={(a) => a.agent}
                label="Agents"
                className="max-h-96 px-3"
                testId="skills-agent-table"
                rowTestId={(a) => `skills-agent-${a.agent}`}
            />
            <p className="max-w-prose px-3 text-xs text-muted-foreground" data-testid="skills-offers">
                {offersText(found)}
            </p>
        </div>
    )
}

/** The agents table's columns, its bar measured against the agents shown. */
function agentColumns(agents: readonly SkillsAgent[]): ReportColumn<SkillsAgent>[] {
    const call = agents.map((a) => a.est_call_tokens)
    return [
        { key: 'agent', kind: 'name', label: 'agent', cell: (a) => <AgentLink agent={a.agent} /> },
        { key: 'runs', kind: 'figure', label: 'runs', hint: RUNS_HINT, cell: (a) => a.runs },
        {
            key: 'none',
            kind: 'figure',
            label: 'no offer',
            hint: NO_OFFER_HINT,
            cell: noOffer,
            tip: noOfferTip,
            tone: (a) => noOffer(a) === 0 && 'text-muted-foreground',
        },
        {
            key: 'skills',
            kind: 'figure',
            label: 'skills',
            hint: AGENT_SKILLS_HINT,
            cell: (a) => a.skills ?? '–',
            tip: (a) => (a.skills === null ? 'no offer on record for any of its runs' : undefined),
            tone: (a) => (a.skills ?? 0) === 0 && 'text-muted-foreground',
        },
        {
            key: 'unused',
            kind: 'figure',
            label: 'never loaded',
            hint: AGENT_UNUSED_HINT,
            cell: (a) => a.unused ?? '–',
            tone: (a) => (a.unused ?? 0) === 0 && 'text-muted-foreground',
        },
        {
            key: 'call',
            kind: 'bar',
            label: '~tokens a call',
            hint: AGENT_CALL_HINT,
            cell: (a) => (a.est_call_tokens === null ? '–' : tokenCount(a.est_call_tokens)),
            tip: agentCallTip,
            bar: (a) => (a.est_call_tokens === null ? null : barPercent(a.est_call_tokens, call)),
            tone: (a) => (a.est_call_tokens ?? 0) === 0 && 'text-muted-foreground',
        },
        {
            key: 'sent',
            kind: 'figure',
            label: 'front matter ~tokens',
            hint: AGENT_SENT_HINT,
            cell: (a) => (a.est_front_matter_tokens === null ? '–' : tokenCount(a.est_front_matter_tokens)),
            tone: (a) => (a.est_front_matter_tokens ?? 0) === 0 && 'text-muted-foreground',
        },
        {
            key: 'loads',
            kind: 'figure',
            label: 'loads',
            hint: AGENT_LOADS_HINT,
            cell: (a) => a.loads,
            tip: agentLoadsTip,
            tone: (a) => a.loads === 0 && 'text-muted-foreground',
        },
    ]
}

/** An agent's name, which picks it for the skills table: its rows are then that agent's own. */
function AgentLink({ agent }: { agent: string }) {
    return (
        // The router marks the picked one's link `aria-current="page"`: its search is the page's own.
        <Link
            to="/reports/skills"
            search={(prev) => ({ ...prev, agent })}
            replace
            resetScroll={false}
            className={cn(
                '-mx-1 block rounded-sm px-1 font-mono text-accent underline-offset-4 hover:underline',
                'aria-[current=page]:bg-accent/16 aria-[current=page]:text-foreground',
            )}
        >
            <Clipped text={agent} mono className="block max-w-64" />
        </Link>
    )
}

/** The skills' order, kept in `?order=`: by front matter, the one the page opens on, or by how often each is loaded. */
function SortToggle() {
    const search = Route.useSearch()
    const navigate = Route.useNavigate()
    return (
        <ToggleGroup
            type="single"
            value={search.order ?? 'cost'}
            aria-label="Sort"
            onValueChange={(value) => {
                const picked = SKILLS_SORTS.find((s) => s.key === value)
                // Pressing the order shown turns it off: keep it. The order the page opens on needs no search.
                if (picked !== undefined) {
                    void navigate({
                        search: (prev) => ({ ...prev, order: picked.key === 'cost' ? undefined : picked.key }),
                        replace: true,
                        resetScroll: false,
                    })
                }
            }}
        >
            {SKILLS_SORTS.map((s) => (
                <ToggleGroupItem key={s.key} value={s.key} data-testid={`skills-sort-${s.key}`}>
                    {s.label}
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}

/**
 * Whose runs the skills table counts, in its header: every agent's, or the picked agent's, by its name, then a link
 * back to every agent's.
 */
function Scope({ picked }: { picked: SkillsAgent | undefined }) {
    return (
        <span className="flex min-w-0 items-center gap-3 text-xs">
            <span className="min-w-0 truncate readout text-muted-foreground" data-testid="skills-scope">
                {picked === undefined ? 'every agent' : picked.agent}
            </span>
            {picked !== undefined && (
                <Link
                    to="/reports/skills"
                    search={(prev) => ({ ...prev, agent: undefined })}
                    // Not the page shown while an agent is: its search drops the agent rather than matching it.
                    activeOptions={{ explicitUndefined: true }}
                    replace
                    resetScroll={false}
                    className="whitespace-nowrap text-accent underline-offset-4 hover:underline"
                >
                    every agent
                </Link>
            )}
        </span>
    )
}

/**
 * Each skill a run was offered or loaded, over every agent or the one picked: the runs offered it and the share that
 * loaded it, its front matter a call and what that came to, with a bar of the most's, then its loads, the calls that
 * failed, and what its text put into context. A skill offered and loaded in no run reads `never` where its rate
 * would. Under the table, what the front matter is counted over.
 */
function Skills({
    found,
    rows,
    picked,
    span,
}: {
    found: SkillsReport
    rows: SkillRow[]
    picked: SkillsAgent | undefined
    span: string
}) {
    return (
        <div className="flex flex-col gap-3 pb-3">
            {rows.length === 0 ? (
                <Empty size="panel">
                    {picked === undefined ? (
                        <>no skill was offered or loaded in these {span}</>
                    ) : (
                        <>
                            no skill was offered to <span className="font-mono">{picked.agent}</span> or loaded by it in
                            these {span}
                        </>
                    )}
                </Empty>
            ) : (
                <ReportTable
                    rows={rows}
                    columns={skillColumns(rows)}
                    rowKey={(r) => r.name}
                    label="Skills"
                    className="max-h-[36rem] px-3"
                    testId="skills-skill-table"
                    rowTestId={(r) => `skills-skill-${r.name}`}
                />
            )}
            <p className="max-w-prose px-3 text-xs text-muted-foreground" data-testid="skills-coverage">
                {coverageText(found)}
            </p>
        </div>
    )
}

/** The skills table's columns, its bar measured against the rows shown. */
function skillColumns(rows: readonly SkillRow[]): ReportColumn<SkillRow>[] {
    const sent = rows.map((r) => r.est_front_matter_tokens)
    return [
        {
            key: 'skill',
            kind: 'name',
            label: 'skill',
            cell: (r) => <Clipped text={r.name} mono className="block max-w-80 font-mono" />,
        },
        {
            key: 'offered',
            kind: 'figure',
            label: 'offered',
            hint: OFFERED_HINT,
            cell: (r) => (r.offered === 0 ? '–' : r.offered),
            tip: (r) => (r.offered === 0 ? 'no offer on record names it' : undefined),
            tone: (r) => r.offered === 0 && 'text-muted-foreground',
        },
        {
            key: 'rate',
            kind: 'figure',
            label: 'load rate',
            hint: RATE_HINT,
            cell: rateText,
            tip: rateTip,
            // `never` is the finding, so it is not muted as a zero would be; a dash, nothing to say, is.
            tone: (r) => rateText(r) === '–' && 'text-muted-foreground',
        },
        {
            key: 'call',
            kind: 'figure',
            label: '~tokens a call',
            hint: CALL_HINT,
            cell: (r) => (r.est_call_tokens === null ? '–' : tokenCount(r.est_call_tokens)),
            tip: (r) =>
                r.front_matter_chars === null
                    ? r.offered === 0
                        ? undefined
                        : UNSIZED
                    : `${r.front_matter_chars} characters of name and description`,
            tone: (r) => r.est_call_tokens === null && 'text-muted-foreground',
        },
        {
            key: 'sent',
            kind: 'bar',
            label: 'front matter ~tokens',
            hint: SENT_HINT,
            cell: (r) => (r.est_front_matter_tokens === null ? '–' : tokenCount(r.est_front_matter_tokens)),
            tip: frontMatterTip,
            bar: (r) => (r.est_front_matter_tokens === null ? null : barPercent(r.est_front_matter_tokens, sent)),
            tone: (r) => r.est_front_matter_tokens === null && 'text-muted-foreground',
        },
        {
            key: 'loads',
            kind: 'figure',
            label: 'loads',
            hint: LOADS_HINT,
            cell: (r) => (r.countable ? r.loads : '–'),
            tip: (r) => (r.countable ? loadsTip(r) : UNNAMED),
            tone: (r) => (!r.countable || r.loads === 0) && 'text-muted-foreground',
        },
        {
            key: 'failed',
            kind: 'figure',
            label: 'failed',
            hint: FAILED_HINT,
            cell: (r) => r.failed,
            tone: (r) => r.failed === 0 && 'text-muted-foreground',
        },
        {
            key: 'body',
            kind: 'figure',
            label: 'body ~tokens',
            hint: BODY_HINT,
            cell: (r) => (r.countable ? tokenCount(r.est_body_tokens) : '–'),
            tip: (r) => (r.countable ? undefined : UNNAMED),
            tone: (r) => (!r.countable || r.est_body_tokens === 0) && 'text-muted-foreground',
        },
    ]
}
