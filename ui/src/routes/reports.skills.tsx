import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { skillsReportQuery } from '@/api/queries'
import type { SkillsAgent, SkillsReport, SkillsSkill } from '@/api/types'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelSkeleton } from '@/components/panel'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { Chip } from '@/components/status'
import { Clipped } from '@/components/tip'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { WindowToggle } from '@/components/window-toggle'
import { barPercent } from '@/lib/chart'
import { readoutDelta, wholeChange } from '@/lib/readout-delta'
import { windowBefore, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import {
    agentNote,
    coverageText,
    DEFAULT_SKILLS_WINDOW,
    loadRate,
    loadsTip,
    runsText,
    sentTip,
    shortAgent,
    SKILLS_SORTS,
    SKILLS_WINDOWS,
    skillsFigures,
    skillsLine,
    skillsSort,
    skillsWindow,
    sortedSkills,
    tokensChange,
    unaskedText,
    cellBar,
    agentUse,
    cellText,
    cellTip,
} from '@/lib/skill-report'
import type { SkillsSort } from '@/lib/skill-report'
import { shareText } from '@/lib/spend'
import { tokenCount } from '@/lib/transcript'

interface SkillsSearch {
    days?: number | undefined
    order?: SkillsSort | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP =
    'Which skills the agents were offered and which they loaded, over the last days: each skill by what its front ' +
    'matter added to the model calls it rode in and by how often a run offered it loaded it, then each skill by ' +
    'agent, and each agent by what its list of skills costs a call. Every count of tokens is an estimate. The page ' +
    "changes no skill: one is denied to an agent in the runtime's own config."

// What a column counts, in its name's tip.
const OFFERED_HINT = 'The runs the runtime said it offered the skill: it rides in each of their model calls'
const LOADED_HINT = 'Of those, the runs that loaded it: a call of the skill tool for it that did not fail'
const RATE_HINT =
    'The runs that loaded it, of the runs offered it. A skill a prompt says to load first, as the ' +
    "tracker's is, is loaded by most runs: that is the prompt at work"
const LOADS_HINT = 'Its loads in every run, offered it on record or not: the calls for it that did not fail'
const TEXT_HINT =
    "About how many tokens its loads put into the runs' context, its text, which each later model call of the run " +
    'reads again: characters over 4, an estimate'
const CALL_HINT =
    'About how many tokens its front matter, its name and description, adds to each model call of a run offered ' +
    'it, as its newest offer recorded it: characters over 4, an estimate'
const SENT_HINT =
    'About how many tokens its front matter added to the model calls of the runs counted, its length at each run ' +
    "times the run's model calls: an estimate. Most are read from the model's cache: context carried, not a price"
const SAID_HINT = 'Its runs the runtime said what it offered: what an offer is counted over'
const AGENT_SKILLS_HINT = 'How many skills its runs were offered, by name'
const AGENT_UNUSED_HINT = 'Of those, the skills none of its runs loaded'
const AGENT_CALL_HINT =
    'About how many tokens the front matter of every skill offered adds to one of its model calls, over the runs ' +
    'counted: characters over 4, an estimate'
const AGENT_SENT_HINT = "About how many tokens that added to the counted runs' model calls, all told: an estimate"

// How to read a cell of the skills by agents grid, under it.
const GRID_KEY =
    "Each figure is the agent's runs that loaded the skill, of its runs offered it, and the bar that share: an empty " +
    'bar is a skill the agent was offered and never loaded, a dash one it was not offered.'

// A chip in a row of figures: as tall as a figure's line, not a chip's own height, so the rows with one keep the pitch
// of those without.
const IN_ROW = 'h-4 align-top'

// What each chip on a skill's row means, in its tip.
const NEVER_LOADED = 'its front matter rode in every one of their model calls all the same.'
const NOT_OFFERED =
    'No run the runtime answered for was offered it: a run it was not asked about loaded it, or a call asked for it ' +
    'and failed.'
const UNCOUNTABLE =
    "The runtime counts a load under a name of lowercase letters, digits, and single hyphens alone: this skill's " +
    'loads are among those that named no skill.'

// A figure the journal cannot say, and why, on its tip.
const UNSIZED = "no offer in this window recorded its description's length"
const UNCOUNTED = "none of its runs is counted: no description's length on record, or no session read"

/**
 * Which skills the agent runs of the last days were offered and loaded, and what each one's front matter cost: each
 * skill, each skill by agent, and each agent. The window is `?days=`, the week or 30 days, and the skills' order
 * `?order=`; the week by front matter, the defaults, need no search.
 */
export const Route = createFileRoute('/reports/skills')({
    // Typed search params: a window or an order the page does not offer is dropped, which reads as its default.
    validateSearch: (search: Record<string, unknown>): SkillsSearch => ({
        days: skillsWindow(search)?.days,
        order: skillsSort(search),
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
    const skills = data === undefined ? [] : sortedSkills(data.skills, search.order)
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
                        onPick={(picked) => {
                            void navigate({
                                search: (prev) => ({
                                    ...prev,
                                    days: picked === DEFAULT_SKILLS_WINDOW ? undefined : picked.days,
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
            <Panel data-testid="skills-by-skill">
                <PanelHeader label="By skill">
                    <span className="flex items-center gap-3">
                        <SortToggle />
                        <span className="readout text-xs text-muted-foreground" data-testid="skills-count">
                            {data?.skills.length ?? ''}
                        </span>
                    </span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelLoading query={query} rows={6} className="min-h-48" />
                ) : (
                    <BySkill found={data} skills={skills} span={span} />
                )}
            </Panel>
            {!failed && (
                <>
                    <Panel data-testid="skills-by-skill-and-agent">
                        <PanelHeader label="By skill and agent" />
                        {data === undefined ? (
                            <PanelSkeleton rows={6} className="min-h-48" />
                        ) : (
                            <BySkillAndAgent agents={data.agents} skills={skills} span={span} />
                        )}
                    </Panel>
                    <Panel data-testid="skills-by-agent">
                        <PanelHeader label="By agent">
                            <span className="readout text-xs text-muted-foreground">{data?.agents.length ?? ''}</span>
                        </PanelHeader>
                        {data === undefined ? (
                            <PanelSkeleton rows={4} className="min-h-32" />
                        ) : (
                            <ByAgent agents={data.agents} span={span} />
                        )}
                    </Panel>
                </>
            )}
        </>
    )
}

/**
 * The window's headline figures, each held in its place while the report is read, and each against the window
 * before's: fewer skills never loaded is better; the front matter, a cost, is never colored, and has no figure while
 * no run is counted for one. Its total grows with the runs counted, so it is compared with the window before only
 * through the mean of a call, which does not.
 */
function skillsTiles(found: SkillsReport | undefined): ReadoutTile[] {
    const figures = found === undefined ? undefined : skillsFigures(found)
    const before = found === undefined ? undefined : skillsFigures(found.previous)
    return [
        {
            key: 'offered',
            label: 'skills offered',
            hint: 'The skills a run was offered, by name: each rides in every model call of a run offered it',
            value: figures?.offered,
            delta: readoutDelta(figures?.offered, before?.offered, wholeChange),
        },
        {
            key: 'unused',
            label: 'never loaded',
            hint: 'Of those, the skills no run of any agent loaded',
            value: figures?.unused,
            delta: readoutDelta(figures?.unused, before?.unused, wholeChange, 'down'),
        },
        {
            key: 'loads',
            label: 'loads',
            hint: 'The calls of the skill tool that did not fail, of every skill canopy could name',
            value: figures?.loads,
            delta: readoutDelta(figures?.loads, before?.loads, wholeChange),
        },
        {
            key: 'call',
            label: '~tokens a call',
            hint:
                "About how many tokens the skills' names and descriptions add to one model call, the mean of the " +
                'calls counted: characters over 4, an estimate',
            value: figures === undefined ? undefined : figures.call === null ? '–' : tokenCount(figures.call),
            delta: readoutDelta(figures?.call, before?.call, tokensChange),
        },
        {
            key: 'sent',
            label: 'front matter ~tokens',
            hint:
                "About how many tokens the skills' names and descriptions added to the model calls of the runs " +
                "counted: an estimate. Most are read from the model's cache: context carried, not a price",
            value: figures === undefined ? undefined : figures.sent === null ? '–' : tokenCount(figures.sent),
        },
    ]
}

/** The skills' order, kept in `?order=`: by front matter sent, the one the page opens on, or by another figure. */
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
 * Each skill a run was offered or loaded: the runs offered it, those that loaded it and their share as a bar, then
 * its front matter, a call and over the window, with a bar of the most's, so what a skill costs sits by how often it
 * is loaded; then its loads and what they put into context. A chip says what a row's figures mean where they could
 * mislead. Under it, what the front matter is counted over.
 */
function BySkill({ found, skills, span }: { found: SkillsReport; skills: SkillsSkill[]; span: string }) {
    if (skills.length === 0) {
        return <Empty size="panel">no skill offered or loaded in these {span}</Empty>
    }
    return (
        <div className="flex flex-col gap-3 pb-3">
            <ReportTable
                rows={skills}
                columns={skillColumns(skills)}
                rowKey={(s) => s.name}
                label="By skill"
                className="max-h-[32rem] px-3"
                testId="skills-skill-table"
                rowTestId={(s) => `skills-skill-${s.name}`}
            />
            <p className="max-w-prose px-3 text-xs text-muted-foreground" data-testid="skills-coverage">
                {coverageText(found)}
            </p>
        </div>
    )
}

/** By skill's columns, the last two bars measured against the rows shown. */
function skillColumns(skills: readonly SkillsSkill[]): ReportColumn<SkillsSkill>[] {
    const sent = skills.map((s) => s.est_sent_tokens)
    return [
        {
            key: 'skill',
            kind: 'name',
            label: 'skill',
            cell: (s) => <Clipped text={s.name} mono className="block max-w-64 font-mono" />,
        },
        {
            key: 'offered',
            kind: 'figure',
            label: 'offered',
            hint: OFFERED_HINT,
            cell: (s) => s.offered,
            tip: (s) => (s.offered === 0 ? undefined : `to ${agentsOffered(s)}`),
            tone: (s) => s.offered === 0 && 'text-muted-foreground',
        },
        {
            key: 'loaded',
            kind: 'figure',
            label: 'loaded',
            hint: LOADED_HINT,
            cell: (s) => (s.countable ? s.loaded : '–'),
            tone: (s) => s.loaded === 0 && 'text-muted-foreground',
        },
        {
            key: 'rate',
            kind: 'bar',
            label: 'load rate',
            hint: RATE_HINT,
            cell: (s) => (s.countable ? shareText(loadRate(s)) : '–'),
            bar: (s) => (s.countable && s.offered > 0 ? (s.loaded / s.offered) * 100 : null),
            tone: (s) => (!s.countable || s.loaded === 0) && 'text-muted-foreground',
        },
        {
            key: 'call',
            kind: 'figure',
            label: '~tokens a call',
            hint: CALL_HINT,
            cell: (s) => (s.est_front_matter_tokens === null ? '–' : tokenCount(s.est_front_matter_tokens)),
            tip: (s) =>
                s.front_matter_chars === null
                    ? s.offered === 0
                        ? undefined
                        : UNSIZED
                    : `${s.front_matter_chars} characters of name and description`,
            tone: (s) => s.est_front_matter_tokens === null && 'text-muted-foreground',
        },
        {
            key: 'sent',
            kind: 'bar',
            label: '~tokens sent',
            hint: SENT_HINT,
            cell: (s) => (s.counted === 0 ? '–' : tokenCount(s.est_sent_tokens)),
            tip: sentTip,
            bar: (s) => (s.counted === 0 ? null : barPercent(s.est_sent_tokens, sent)),
            tone: (s) => s.counted === 0 && 'text-muted-foreground',
        },
        {
            key: 'loads',
            kind: 'figure',
            label: 'loads',
            hint: LOADS_HINT,
            cell: (s) => (s.countable ? s.loads : '–'),
            tip: loadsTip,
            tone: (s) => s.loads === 0 && 'text-muted-foreground',
        },
        {
            key: 'text',
            kind: 'figure',
            label: '~tokens loaded',
            hint: TEXT_HINT,
            cell: (s) => (s.countable ? tokenCount(s.est_result_tokens) : '–'),
            tone: (s) => s.est_result_tokens === 0 && 'text-muted-foreground',
        },
        { key: 'says', kind: 'word', label: null, cell: (s) => <Verdict skill={s} /> },
    ]
}

// How many agents a skill was offered to, in words: `2 agents`.
function agentsOffered(skill: SkillsSkill): string {
    const n = skill.uses.filter((u) => u.offered > 0).length
    return n === 1 ? '1 agent' : `${n} agents`
}

/**
 * What a skill's row means where its figures alone could mislead, as a chip of fixed words: offered and never loaded;
 * loaded or asked for with no offer on record; or named outside the runtime's rule, so its loads count under no name.
 */
function Verdict({ skill }: { skill: SkillsSkill }) {
    if (!skill.countable) {
        return <Chip word="loads not counted" meaning={UNCOUNTABLE} className={IN_ROW} />
    }
    if (skill.offered === 0) {
        return <Chip word="not offered" meaning={NOT_OFFERED} className={IN_ROW} />
    }
    return skill.unused ? (
        <Chip
            word="never loaded"
            meaning={`Offered in ${runsText(skill.offered)}, and none of any agent's loaded it: ${NEVER_LOADED}`}
            className={IN_ROW}
        />
    ) : null
}

/**
 * Each skill against each agent, in the skills' order: the agent's runs that loaded it of its runs offered it, with a
 * bar of that share, so a skill an agent is offered and never loads shows an empty bar, and one it is not offered, a
 * dash and no bar. Under it, how to read a cell.
 */
function BySkillAndAgent({ agents, skills, span }: { agents: SkillsAgent[]; skills: SkillsSkill[]; span: string }) {
    const offered = agents.filter((a) => a.skills > 0 || skills.some((s) => agentUse(s, a.agent) !== undefined))
    if (skills.length === 0 || offered.length === 0) {
        return <Empty size="panel">no skill offered or loaded in these {span}</Empty>
    }
    return (
        <div className="flex flex-col gap-3 pb-3">
            <ReportTable
                rows={skills}
                columns={gridColumns(offered)}
                rowKey={(s) => s.name}
                label="By skill and agent"
                className="max-h-[32rem] overflow-x-auto px-3"
                testId="skills-grid"
                rowTestId={(s) => `skills-grid-${s.name}`}
            />
            <p className="max-w-prose px-3 text-xs text-muted-foreground" data-testid="skills-grid-key">
                {GRID_KEY}
            </p>
        </div>
    )
}

/** The grid's columns: the skill, then a bar per agent, headed by the agent's name without canopy's prefix. */
function gridColumns(agents: readonly SkillsAgent[]): ReportColumn<SkillsSkill>[] {
    return [
        {
            key: 'skill',
            kind: 'name',
            label: 'skill',
            cell: (s) => <Clipped text={s.name} mono className="block max-w-64 font-mono" />,
        },
        ...agents.map((a): ReportColumn<SkillsSkill> => ({
            key: a.agent,
            kind: 'bar',
            label: shortAgent(a.agent),
            hint: `${a.agent}: its runs that loaded each skill, of its runs offered it`,
            cell: (s) =>
                s.countable ? cellText(agentUse(s, a.agent)) : agentUse(s, a.agent) === undefined ? '–' : 'offered',
            tip: (s) => cellTip(agentUse(s, a.agent)),
            bar: (s) => (s.countable ? cellBar(agentUse(s, a.agent)) : null),
            tone: (s) => {
                const use = agentUse(s, a.agent)
                return (use === undefined || use.loads === 0) && 'text-muted-foreground'
            },
        })),
    ]
}

/**
 * Each agent that ran: its runs and those the runtime answered for, the skills it was offered and how many it never
 * loaded, then what their front matter adds to one of its model calls, with a bar of the most's, and over the
 * window. A note says what the figures leave out. Under it, the runs no offer is counted for.
 */
function ByAgent({ agents, span }: { agents: SkillsAgent[]; span: string }) {
    if (agents.length === 0) {
        return <Empty size="panel">no agent ran in these {span}</Empty>
    }
    const unasked = unaskedText(agents)
    return (
        <div className="flex flex-col gap-3 pb-3">
            <ReportTable
                rows={agents}
                columns={agentColumns(agents)}
                rowKey={(a) => a.agent}
                label="By agent"
                className="max-h-96 px-3"
                testId="skills-agent-table"
                rowTestId={(a) => `skills-agent-${a.agent}`}
            />
            {unasked !== '' && (
                <p className="max-w-prose px-3 text-xs text-muted-foreground" data-testid="skills-unasked">
                    {unasked}
                </p>
            )}
        </div>
    )
}

/** By agent's columns, the bar measured against the agents shown. */
function agentColumns(agents: readonly SkillsAgent[]): ReportColumn<SkillsAgent>[] {
    const call = agents.map((a) => a.est_call_tokens)
    return [
        {
            key: 'agent',
            kind: 'name',
            label: 'agent',
            cell: (a) => <Clipped text={a.agent} mono className="block max-w-64 font-mono" />,
        },
        { key: 'runs', kind: 'figure', label: 'runs', cell: (a) => a.runs },
        {
            key: 'said',
            kind: 'figure',
            label: 'answered for',
            hint: SAID_HINT,
            cell: (a) => a.said,
            muted: true,
        },
        {
            key: 'skills',
            kind: 'figure',
            label: 'skills',
            hint: AGENT_SKILLS_HINT,
            cell: (a) => (a.said === 0 ? '–' : a.skills),
            tone: (a) => a.skills === 0 && 'text-muted-foreground',
        },
        {
            key: 'unused',
            kind: 'figure',
            label: 'never loaded',
            hint: AGENT_UNUSED_HINT,
            cell: (a) => (a.said === 0 ? '–' : a.unused),
            tone: (a) => a.unused === 0 && 'text-muted-foreground',
        },
        {
            key: 'call',
            kind: 'bar',
            label: '~tokens a call',
            hint: AGENT_CALL_HINT,
            cell: (a) => (a.est_call_tokens === null ? '–' : tokenCount(a.est_call_tokens)),
            tip: (a) =>
                a.est_call_tokens === null
                    ? a.said === 0
                        ? undefined
                        : UNCOUNTED
                    : `over ${a.counted} of ${a.said} runs, ${a.calls} model calls`,
            bar: (a) => (a.est_call_tokens === null ? null : barPercent(a.est_call_tokens, call)),
            tone: (a) => (a.est_call_tokens ?? 0) === 0 && 'text-muted-foreground',
        },
        {
            key: 'sent',
            kind: 'figure',
            label: '~tokens sent',
            hint: AGENT_SENT_HINT,
            cell: (a) => (a.counted === 0 ? '–' : tokenCount(a.est_sent_tokens)),
            tone: (a) => a.est_sent_tokens === 0 && 'text-muted-foreground',
        },
        {
            key: 'note',
            kind: 'free',
            label: null,
            cell: (a) => <span className="text-muted-foreground">{agentNote(a)}</span>,
        },
    ]
}
