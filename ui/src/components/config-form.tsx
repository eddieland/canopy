import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation } from '@tanstack/react-router'
import { LockKeyhole, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { refreshReloaded, saveConfig } from '@/api/mutations'
import { configQuery } from '@/api/queries'
import type { ConfigKey, ConfigSaved, ConfigSettings, ConfigValue } from '@/api/types'
import { CopyButton } from '@/components/copy-button'
import { Disclosure } from '@/components/disclosure'
import { FilterField } from '@/components/filter-field'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { Empty, Panel, PanelSkeleton } from '@/components/panel'
import { RepoSelect } from '@/components/repo-picker'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
    bandCounts,
    bandsMatching,
    boundText,
    byPart,
    changeList,
    CONFIG_QUERY_MAX,
    configForm,
    configQueryOf,
    groupedKeys,
    groupSlug,
    oneWay,
    oneWayText,
    pendingText,
    REPO_SLOTS,
    savedText,
    SOURCE_MEANING,
    SOURCE_WORD,
    unsetText,
    valueText,
} from '@/lib/config-settings'
import type { ConfigChange, ConfigDrafts, LabelledKey } from '@/lib/config-settings'
import { SECTION_TEXT } from '@/lib/sections'
import { cn } from '@/lib/utils'

// The trust switches, and the side the page may move each to: the stricter one (TRUST_MODEL T8).
const STRICTER_ON: Record<string, boolean> = { 'trust.rebase': false, 'trust.commit_trailer': true }
// How many changes the save bar lists before it folds the rest away.
const LISTED = 3
// The save bar's list of changes, folded in two past `LISTED`.
const CHANGES = 'flex min-w-0 max-w-full flex-col font-mono text-xs text-muted-foreground'
// Every field's box, one width, so the control column has one edge.
const FIELD_WIDTH = 'readout h-8 w-28 text-right'
// A row: its label, then its control in one fixed column, which every row shares so the controls line up; stacked
// in a panel too narrow for both.
const ROW = 'grid gap-x-6 gap-y-2 p-3 @xl:grid-cols-[minmax(0,1fr)_18rem] @xl:items-center'
// A changed row's mark: an accent hairline at its start, drawn over its padding, so nothing in it moves.
const CHANGED_ROW = 'relative before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-accent'

/**
 * The Loop settings form: the keys the loop reads that the web UI may change, edited in place (DESIGN §22, M41):
 * counts, paces, and retentions within the bounds the server sets, and trust settings only toward stricter. The keys
 * come in bands by what they govern (`CONFIG_GROUPS`), a band of several kinds in labelled parts, each key in words
 * over its name in the file. A changed row is marked, and a save bar, kept in view at the page's foot once something
 * changed, lists the changes and writes them at once. A save writes the workspace's private file alone, keeping its
 * comments, then asks the loop to read it again as Reload does. An index of the bands sits beside the form, sticking as
 * it scrolls, or in a line over it in a narrower pane; each row is its key's anchor, `#policy.max_resume_attempts`.
 */
export function ConfigForm({
    q,
    onFilter,
}: {
    /** The page's `?q=`: only the rows whose label, key, or band's blurb holds it show, and every unsaved one. */
    q: string | undefined
    /** Sets the page's `?q=`. */
    onFilter: (query: string | undefined) => void
}) {
    const client = useQueryClient()
    const { data, error } = useQuery(configQuery)
    // Here, not in the form: a save reads the file again, and the form over the new read keeps what the save said.
    const mutation = useMutation({
        mutationFn: ({ hash, changes }: { hash: string; changes: Record<string, ConfigValue> }) =>
            saveConfig(hash, changes),
        onSuccess: () => refreshReloaded(client),
    })
    if (data === undefined) {
        return (
            <Panel className="min-h-72" data-testid="config-form">
                {error ? <Notice error={error} className="p-3" /> : <PanelSkeleton rows={8} />}
            </Panel>
        )
    }
    return (
        <Form
            key={data.hash}
            settings={data}
            saving={mutation.isPending}
            saved={mutation.data}
            refused={mutation.error}
            onSave={(changes) => mutation.mutate({ hash: data.hash, changes })}
            q={q}
            onFilter={onFilter}
        />
    )
}

/**
 * The path of the workspace's private config, the file a save writes, as the page read it, for the page's header, with
 * a button that copies it. Nothing until the read names it, so the page never points at a file it has not read.
 */
export function ConfigFile() {
    const path = useQuery(configQuery).data?.private_file
    if (path === undefined) {
        return null
    }
    return (
        <span className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
            saves to
            <code className="truncate font-mono" data-testid="config-private-file" title={path}>
                {path}
            </code>
            <CopyButton text={path} label="config path" />
        </span>
    )
}

/** The form over one read of the file: a new read, after a save, starts it afresh with nothing typed. */
function Form({
    settings,
    saving,
    saved,
    refused,
    onSave,
    q,
    onFilter,
}: {
    settings: ConfigSettings
    saving: boolean
    saved: ConfigSaved | undefined
    refused: Error | null
    onSave: (changes: Record<string, ConfigValue>) => void
    q: string | undefined
    onFilter: (query: string | undefined) => void
}) {
    const [drafts, setDrafts] = useState<ConfigDrafts>({})
    const form = configForm(settings.keys, drafts)
    // Counted as the bar lists them: each repository's own count is a change of its own.
    const changed = changeList(settings.keys, form.changes)
    const pending = changed.length
    const errors = Object.keys(form.errors).length
    const touched = (name: string) =>
        name in form.changes || Object.keys(form.errors).some((n) => n === name || n.startsWith(`${name}.`))
    // Shown once something changed, and kept while a save's outcome has something to say.
    const barShown = pending + errors > 0 || saved !== undefined || refused !== null
    const stricter = oneWay(settings.keys, form.changes)
    const draft = (name: string, value: ConfigDrafts[string]) => setDrafts({ ...drafts, [name]: value })
    const perRepo = settings.keys.find((k) => k.name === 'capacity.slots_per_repo')?.value
    const bands = groupedKeys(settings.keys)
    // What the filter leaves: each band's rows that match, and every unsaved one; a band with none is not drawn.
    const matched = bandsMatching(bands, q, touched)
    const drawn = matched.filter(({ keys }) => keys.length > 0)
    const matching = drawn.reduce((count, { keys }) => count + keys.length, 0)
    const inView = useBandInView(drawn.map(({ group }) => bandId(group.title)).join(' '))
    // The row the page was opened at (`#capacity.max_workers`): scrolled to, and lit once, until its light has played.
    const hash = useLocation({ select: (location) => location.hash })
    const [lit, setLit] = useState<string>()
    const target = hash === lit ? undefined : hash
    useEffect(() => {
        if (hash !== '') {
            // A band's top, as the index links to it; a row in the middle of the page, where its light is seen.
            document
                .querySelector(`#${CSS.escape(hash)}`)
                ?.scrollIntoView({ block: hash.startsWith('band-') ? 'start' : 'center' })
        }
    }, [hash])
    const row = ({ setting, label, unit }: LabelledKey) =>
        setting.name === REPO_SLOTS ? (
            <RepoSlots
                key={setting.name}
                setting={setting}
                label={label}
                repos={settings.repos}
                perRepo={typeof perRepo === 'number' ? perRepo : null}
                draft={drafts[setting.name]}
                changed={touched(setting.name)}
                lit={target === setting.name}
                onLit={() => setLit(setting.name)}
                errors={form.errors}
                onDraft={(value) => draft(setting.name, value)}
            />
        ) : (
            <li
                key={setting.name}
                id={setting.name}
                className={cn(ROW, touched(setting.name) && CHANGED_ROW, target === setting.name && 'animate-lit')}
                data-changed={touched(setting.name) || undefined}
                onAnimationEnd={(event) => {
                    if (event.target === event.currentTarget) {
                        setLit(setting.name)
                    }
                }}
            >
                <KeyLabel setting={setting} label={label} every={settings.every} changed={touched(setting.name)} />
                <ControlCell unit={unit}>
                    <Control
                        setting={setting}
                        draft={drafts[setting.name]}
                        error={form.errors[setting.name]}
                        onDraft={(value) => draft(setting.name, value)}
                    />
                </ControlCell>
                <FieldError name={setting.name} error={form.errors[setting.name]} />
            </li>
        )
    return (
        <div className="@container">
            {/* Two columns once the pane has room for the index beside the form at full size, about 72rem. Written
                out, so Tailwind finds them. */}
            <div className="grid grid-cols-1 gap-x-8 gap-y-6 @min-[72rem]:grid-cols-[12rem_minmax(0,56rem)]">
                <nav
                    aria-label="Bands"
                    className={cn(
                        'flex flex-wrap gap-x-4 gap-y-1',
                        '@min-[72rem]:sticky @min-[72rem]:top-0 @min-[72rem]:flex-col @min-[72rem]:self-start',
                    )}
                    data-testid="config-index"
                >
                    {bands.map(({ group, keys: shown }, i) => (
                        <BandLink
                            key={group.title}
                            title={group.title}
                            current={inView === bandId(group.title)}
                            hidden={matched[i]?.keys.length === 0}
                            {...bandCounts(shown, touched)}
                        />
                    ))}
                </nav>
                <div className="flex max-w-4xl min-w-0 flex-col gap-6">
                    {/* Outside the form, so Enter in it filters and never saves. */}
                    <search>
                        <FilterField
                            q={q}
                            queryOf={configQueryOf}
                            onFilter={onFilter}
                            label="Filter settings by label or key"
                            placeholder="Filter by label or key"
                            maxLength={CONFIG_QUERY_MAX}
                            clearOnEscape
                            end={
                                q === undefined ? undefined : (
                                    <span className="readout shrink-0 text-xs text-muted-foreground">
                                        {matching} of {settings.keys.length}
                                    </span>
                                )
                            }
                        />
                    </search>
                    <form
                        className="flex min-w-0 flex-col gap-8"
                        aria-label="Loop settings"
                        data-testid="config-form"
                        onSubmit={(event) => {
                            event.preventDefault()
                            onSave(form.changes)
                        }}
                    >
                        {drawn.length === 0 && (
                            <Panel>
                                <Empty>no setting&apos;s label or key holds “{q}”</Empty>
                            </Panel>
                        )}
                        {drawn.map(({ group, keys: shown }) => (
                            <section
                                key={group.title}
                                id={bandId(group.title)}
                                aria-labelledby={`${bandId(group.title)}-heading`}
                                className="flex scroll-mt-4 flex-col gap-2"
                                data-testid={`config-group-${groupSlug(group.title)}`}
                            >
                                {/* A band's heading stands over its panel, a step above the rows' labels, in Settings'
                                color. */}
                                <div className="flex flex-col gap-0.5">
                                    <h2
                                        id={`${bandId(group.title)}-heading`}
                                        className={cn('text-base font-semibold', SECTION_TEXT['/settings'])}
                                    >
                                        {group.title}
                                    </h2>
                                    <p className="text-xs text-muted-foreground">{group.blurb}</p>
                                </div>
                                <Panel>
                                    {byPart(shown).map(({ part, keys: inPart }) => (
                                        <section
                                            key={part ?? ''}
                                            className="border-b last:border-b-0"
                                            aria-label={part}
                                        >
                                            {part !== undefined && (
                                                <h3
                                                    className={cn(
                                                        'border-b bg-surface-raised/50 px-3 py-2',
                                                        'panel-label text-foreground',
                                                    )}
                                                >
                                                    {part}
                                                </h3>
                                            )}
                                            <ul className="divide-y">{inPart.map((k) => row(k))}</ul>
                                        </section>
                                    ))}
                                </Panel>
                            </section>
                        ))}
                        {/* Kept in view at the page's foot once something changed, so a change made far down the
                        page is never left unsaved unseen. Until then its height is held at the page's end, so its
                        coming moves nothing. */}
                        {barShown ? (
                            <Panel className="sticky bottom-4 z-10 min-h-16 shadow-float" data-testid="config-save-bar">
                                <div className="flex items-start justify-between gap-4 p-3">
                                    <div className="flex min-w-0 flex-col gap-1">
                                        <p className="text-sm text-foreground" data-testid="config-pending">
                                            {pendingText(pending, errors)}
                                        </p>
                                        <ChangeList changes={changed} />
                                        {stricter.length > 0 && (
                                            <p
                                                className="flex items-center gap-1.5 text-xs text-status-blocked"
                                                data-testid="config-one-way"
                                            >
                                                <LockKeyhole aria-hidden className="size-3 shrink-0" />
                                                {oneWayText(stricter)}
                                            </p>
                                        )}
                                        {/* A field in error says why on its own row; this is what the server said of a
                                        save. */}
                                        <Notice error={refused}>{saved ? savedText(saved) : null}</Notice>
                                    </div>
                                    <SaveActions
                                        pending={pending}
                                        errors={errors}
                                        saving={saving}
                                        onDiscard={() => setDrafts({})}
                                    />
                                </div>
                            </Panel>
                        ) : (
                            <div aria-hidden className="min-h-16" />
                        )}
                    </form>
                </div>
            </div>
        </div>
    )
}

/** A band's id on the page, which its index entry links to: `band-retention-budget`. */
function bandId(title: string): string {
    return `band-${groupSlug(title)}`
}

/**
 * The band most in view, by its id, of the bands `ids` names (space-separated, in page order): the first whose panel
 * crosses the top half of the page's scroll. Undefined until the page has scrolled them into view, or where the browser
 * cannot say.
 */
function useBandInView(ids: string): string | undefined {
    const [shown, setShown] = useState<ReadonlySet<string>>(new Set())
    useEffect(() => {
        if (typeof IntersectionObserver === 'undefined') {
            return
        }
        const observer = new IntersectionObserver(
            (entries) =>
                setShown((was) => {
                    const now = new Set(was)
                    for (const entry of entries) {
                        if (entry.isIntersecting) {
                            now.add(entry.target.id)
                        } else {
                            now.delete(entry.target.id)
                        }
                    }
                    return now
                }),
            // The top half of the scroll: a band counts once it reaches there, and until it leaves the top.
            { rootMargin: '0px 0px -50% 0px' },
        )
        for (const id of ids.split(' ').filter((one) => one !== '')) {
            const band = document.querySelector(`#${CSS.escape(id)}`)
            if (band !== null) {
                observer.observe(band)
            }
        }
        return () => observer.disconnect()
    }, [ids])
    return ids.split(' ').find((id) => shown.has(id))
}

/**
 * A band's entry in the page's index: its title, linking to it, then how many of its keys this workspace sets and how
 * many of its rows wait unsaved, each left out at none. The band most in view is marked current, in the foreground,
 * and one the filter left empty is dimmed.
 */
function BandLink({
    title,
    current,
    hidden,
    set,
    changed,
}: {
    title: string
    current: boolean
    /** Whether the filter left the band no row to show: it stays, dimmed, so the index keeps its shape. */
    hidden: boolean
    set: number
    changed: number
}) {
    return (
        <Link
            to="/settings/limits"
            // The filter stays as it is: a band link moves the page, not what it shows.
            search
            hash={bandId(title)}
            // Only the band the address names is the link to where you are, not all five: they share a path.
            activeOptions={{ includeHash: true }}
            data-current={current || undefined}
            data-hidden={hidden || undefined}
            className={cn(
                'flex items-baseline gap-2 py-0.5 text-sm text-muted-foreground hover:text-foreground',
                'data-current:text-foreground data-hidden:opacity-50',
            )}
            data-testid={`config-index-${groupSlug(title)}`}
        >
            <span className={cn(current && 'font-medium')}>{title}</span>
            {set > 0 && (
                <span className="readout text-2xs" title={`${set} set in this workspace`}>
                    {set} set
                </span>
            )}
            {changed > 0 && (
                <span className="readout text-2xs text-accent" title={`${changed} changed, not saved`}>
                    {changed} unsaved
                </span>
            )}
        </Link>
    )
}

/** The save bar's Discard and Save, each off until something changed; Save off too while a field is in error. */
function SaveActions({
    pending,
    errors,
    saving,
    onDiscard,
}: {
    pending: number
    errors: number
    saving: boolean
    onDiscard: () => void
}) {
    return (
        <span className="flex shrink-0 items-center gap-2">
            <Button
                type="button"
                variant="ghost"
                disabled={pending + errors === 0 || saving}
                data-testid="config-discard"
                onClick={onDiscard}
            >
                Discard
            </Button>
            <Button
                type="submit"
                disabled={pending === 0 || errors > 0 || saving}
                // A disabled action has nothing to lift: the accent's glow goes with its fill's strength.
                className="disabled:shadow-none"
                data-testid="config-save"
            >
                <Save />
                Save
            </Button>
        </span>
    )
}

/**
 * What a save would change, one `key: old → new` a line, in the CLI's monospace; past `LISTED`, the rest folded under
 * a disclosure, so a long list never pushes Save off the screen.
 */
function ChangeList({ changes }: { changes: ConfigChange[] }) {
    const [open, setOpen] = useState(false)
    if (changes.length === 0) {
        return null
    }
    const rest = changes.slice(LISTED)
    return (
        <Collapsible open={open} onOpenChange={setOpen} className="flex flex-col items-start gap-0.5">
            <ul className={CHANGES} data-testid="config-changes">
                {changes.slice(0, LISTED).map((c) => (
                    <ChangeLine key={c.name} change={c} />
                ))}
            </ul>
            <CollapsibleContent asChild>
                <ul className={CHANGES}>
                    {rest.map((c) => (
                        <ChangeLine key={c.name} change={c} />
                    ))}
                </ul>
            </CollapsibleContent>
            {rest.length > 0 && <Disclosure open={open} what={`${rest.length} more`} className="-ml-2" />}
        </Collapsible>
    )
}

/** One change a save would make, as `key: old → new`. */
function ChangeLine({ change }: { change: ConfigChange }) {
    return (
        <li className="truncate">
            {change.name}: {change.old} → {change.new}
        </li>
    )
}

/**
 * A key in words, and under it its name in the file, a chip for where its value comes from, how far the page may take
 * it, and, once `changed`, its value as read.
 */
function KeyLabel({
    setting,
    label,
    every,
    changed = false,
}: {
    setting: ConfigKey
    label: string
    every: number | null
    changed?: boolean
}) {
    // A repository's own counts list their old values in the save bar; a row of them says nothing of one.
    const was = changed && setting.name !== REPO_SLOTS ? `was ${valueText(setting.value, setting.name)}` : null
    const pace =
        setting.name === 'loop.interval_minutes' && every !== null
            ? `--every ${every} sets the pace until the loop restarts`
            : null
    const rest = [boundText(setting), was, pace].filter(Boolean).join(' · ')
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <span className="text-sm text-foreground">{label}</span>
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-muted-foreground">
                <code className="font-mono">{setting.name}</code>
                <Chip word={SOURCE_WORD[setting.source]} meaning={SOURCE_MEANING[setting.source]} />
                {rest === '' ? null : <span>{rest}</span>}
            </span>
        </div>
    )
}

/**
 * `capacity.repo_slots`: a row per repository the file gives a count of its own, and a field to give one to another.
 * A workspace of many repositories shows only the few that differ from `capacity.slots_per_repo`, not a field each.
 */
function RepoSlots({
    setting,
    label,
    repos,
    perRepo,
    draft,
    changed,
    lit,
    onLit,
    errors,
    onDraft,
}: {
    setting: ConfigKey
    label: string
    repos: string[]
    perRepo: number | null
    draft: ConfigDrafts[string] | undefined
    changed: boolean
    /** Whether the page was opened at this row, which lights once. */
    lit: boolean
    /** Called once its light has played. */
    onLit: () => void
    errors: Record<string, string>
    onDraft: (value: ConfigDrafts[string]) => void
}) {
    const { name, value } = setting
    const counts = typeof value === 'object' && value !== null && !Array.isArray(value) ? value : {}
    const typed = typeof draft === 'object' && !Array.isArray(draft) ? draft : {}
    const shown = [...new Set([...Object.keys(counts), ...Object.keys(typed)])].toSorted()
    // The workspace's repositories with no count of their own yet; the private file is this workspace's alone.
    const offered = repos.filter((r) => !shown.includes(r))
    const fallback = perRepo === null ? 'unmanaged' : String(perRepo)
    return (
        <li
            id={name}
            className={cn(ROW, changed && CHANGED_ROW, lit && 'animate-lit')}
            data-changed={changed || undefined}
            data-testid="repo-slots"
            onAnimationEnd={(event) => {
                if (event.target === event.currentTarget) {
                    onLit()
                }
            }}
        >
            <KeyLabel setting={setting} label={label} every={null} changed={changed} />
            {shown.length === 0 ? (
                <p className="text-xs text-muted-foreground @xl:col-start-1">
                    no repository has its own count yet: each pool has the slots per repository ({fallback})
                </p>
            ) : (
                <ul className="col-span-full flex flex-col gap-1">
                    {shown.map((repo) => (
                        <li key={repo} className="grid gap-x-6 gap-y-1 @xl:grid-cols-[minmax(0,1fr)_18rem]">
                            <span className="self-center font-mono text-xs text-foreground">{repo}</span>
                            <ControlCell>
                                <Count
                                    name={`${name}.${repo}`}
                                    text={typed[repo] ?? String(counts[repo] ?? '')}
                                    placeholder={fallback}
                                    error={errors[`${name}.${repo}`]}
                                    onText={(text) => onDraft({ ...typed, [repo]: text })}
                                />
                            </ControlCell>
                            <FieldError name={`${name}.${repo}`} error={errors[`${name}.${repo}`]} />
                        </li>
                    ))}
                </ul>
            )}
            {offered.length > 0 && (
                <span className="col-span-full flex items-center gap-2 text-xs text-muted-foreground">
                    Give another its own count:
                    <RepoSelect
                        choices={offered}
                        value={null}
                        none="pick a repository"
                        label="Repository to give its own count"
                        onValue={(repo) => {
                            if (repo !== null) {
                                onDraft({ ...typed, [repo]: '' })
                            }
                        }}
                    />
                </span>
            )}
        </li>
    )
}

/**
 * A row's control column: its control at the column's end, then its unit (`min`, `days`) in a slot every row keeps,
 * empty or not, so the fields' right edges line up down the page.
 */
function ControlCell({ unit, children }: { unit?: string | undefined; children: ReactNode }) {
    return (
        <div className="flex items-center gap-2 @xl:justify-end">
            {children}
            <span className="readout w-8 shrink-0 text-xs text-muted-foreground">{unit}</span>
        </div>
    )
}

/**
 * The control for one key: a number field, a switch, a choice, a list's entries to keep, or the budget's alerts as
 * typed.
 */
function Control({
    setting,
    draft,
    error,
    onDraft,
}: {
    setting: ConfigKey
    draft: ConfigDrafts[string] | undefined
    error: string | undefined
    onDraft: (value: ConfigDrafts[string]) => void
}) {
    const { name, value } = setting
    if (setting.kind === 'free') {
        return (
            <Input
                aria-label={name}
                {...invalid(name, error)}
                value={typeof draft === 'string' ? draft : Array.isArray(value) ? value.join(', ') : ''}
                placeholder="none"
                className={FIELD_WIDTH}
                data-testid={name}
                onChange={(event) => onDraft(event.currentTarget.value)}
            />
        )
    }
    if (Array.isArray(value)) {
        // A stricter key's entries are names; only the budget's alerts, drawn above, are numbers.
        const entries = value.map(String)
        const kept = Array.isArray(draft) ? draft : entries
        if (entries.length === 0) {
            return <span className="text-xs text-muted-foreground">none</span>
        }
        return (
            <fieldset aria-label={name} className="flex flex-wrap gap-3 @xl:justify-end">
                {entries.map((entry) => (
                    <label key={entry} className="inline-flex items-center gap-2 font-mono text-xs">
                        <Checkbox
                            checked={kept.includes(entry)}
                            data-testid={`${name}-${entry}`}
                            onCheckedChange={(checked) =>
                                onDraft(entries.filter((e) => (e === entry ? checked === true : kept.includes(e))))
                            }
                        />
                        {entry}
                    </label>
                ))}
            </fieldset>
        )
    }
    if (setting.choices.length > 0) {
        // Loosest first: a choice before the one the files give now is looser, and the page does not offer it.
        const current = typeof value === 'string' ? value : ''
        const now = setting.choices.indexOf(current)
        return (
            <ToggleGroup
                type="single"
                value={typeof draft === 'string' ? draft : current}
                aria-label={name}
                data-testid={name}
                onValueChange={(picked) => {
                    if (picked !== '') {
                        onDraft(picked)
                    }
                }}
            >
                {setting.choices.map((choice, i) => (
                    <ToggleGroupItem key={choice} value={choice} disabled={i < now} data-testid={`${name}-${choice}`}>
                        {choice}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        )
    }
    if (typeof value === 'boolean') {
        const strict = STRICTER_ON[name]
        return (
            <label htmlFor={`${name}-field`} className="inline-flex items-center gap-2 text-xs">
                <Checkbox
                    id={`${name}-field`}
                    checked={typeof draft === 'boolean' ? draft : value}
                    disabled={value === strict}
                    data-testid={name}
                    onCheckedChange={(checked) => onDraft(checked === true)}
                />
                on
            </label>
        )
    }
    return (
        <Count
            name={name}
            text={typeof draft === 'string' ? draft : typeof value === 'number' ? String(value) : ''}
            placeholder={value === null ? unsetText(name) : ''}
            error={error}
            onText={onDraft}
        />
    )
}

/**
 * A whole number's field, its value the text as typed: one the form would not send, `error` says why under its row,
 * and the field is marked invalid and points to it.
 */
function Count({
    name,
    text,
    placeholder,
    error,
    onText,
}: {
    name: string
    text: string
    placeholder: string
    error: string | undefined
    onText: (text: string) => void
}) {
    return (
        <Input
            aria-label={name}
            {...invalid(name, error)}
            inputMode="numeric"
            value={text}
            placeholder={placeholder}
            className={FIELD_WIDTH}
            data-testid={name}
            onChange={(event) => onText(event.currentTarget.value)}
        />
    )
}

/** The id of the line that says why field `name` holds what the form would not send. */
function errorId(name: string): string {
    return `${name}-error`
}

/** A field's attributes while it holds what the form would not send: marked invalid, and pointing to why. */
function invalid(name: string, error: string | undefined): { 'aria-invalid'?: true; 'aria-describedby'?: string } {
    return error === undefined ? {} : { 'aria-invalid': true, 'aria-describedby': errorId(name) }
}

/** Why field `name` holds what the form would not send, under its row, in the failure color; nothing when fine. */
function FieldError({ name, error }: { name: string; error: string | undefined }) {
    if (error === undefined) {
        return null
    }
    return (
        <p
            id={errorId(name)}
            className="col-span-full text-xs text-status-failed @xl:text-right"
            data-testid={errorId(name)}
        >
            {error}
        </p>
    )
}
