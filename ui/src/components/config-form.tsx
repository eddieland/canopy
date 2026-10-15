import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Save } from 'lucide-react'
import { useState } from 'react'

import { saveConfig } from '@/api/mutations'
import { configQuery, keys } from '@/api/queries'
import type { ConfigKey, ConfigSaved, ConfigSettings, ConfigValue } from '@/api/types'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
    boundText,
    configForm,
    groupedKeys,
    pendingText,
    REPO_SLOTS,
    savedText,
    sourceText,
} from '@/lib/config-settings'
import type { ConfigDrafts } from '@/lib/config-settings'

// The trust switches, and the side the page may move each to: the stricter one (TRUST_MODEL T8).
const STRICTER_ON: Record<string, boolean> = { 'trust.rebase': false, 'trust.commit_trailer': true }
const STACKING = 'policy.stacking'

/**
 * The limits and trust settings the loop reads from the user config, edited in place (DESIGN §22, M41): counts and
 * paces within the bounds the server sets, and trust settings only toward stricter. The keys come in panels by what
 * they govern (`CONFIG_GROUPS`), each in words over its name in the file, and one save bar, kept in view at the page's
 * foot, writes every change at once. A save writes the user file alone, keeping its comments, then asks the loop to
 * read it again as Reload does.
 */
export function ConfigForm() {
    const client = useQueryClient()
    const { data, error } = useQuery(configQuery)
    // Here, not in the form: a save reads the file again, and the form over the new read keeps what the save said.
    const mutation = useMutation({
        mutationFn: ({ hash, changes }: { hash: string; changes: Record<string, ConfigValue> }) =>
            saveConfig(hash, changes),
        onSuccess: () => client.invalidateQueries({ queryKey: keys.config }),
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
        />
    )
}

/** The user config's path, as the page read it, for the page's header; nothing while the first read is on its way. */
export function ConfigFile() {
    const path = useQuery(configQuery).data?.user_file
    return (
        <code className="font-mono text-xs" data-testid="config-user-file">
            {path ?? 'config.toml'}
        </code>
    )
}

/** The form over one read of the file: a new read, after a save, starts it afresh with nothing typed. */
function Form({
    settings,
    saving,
    saved,
    refused,
    onSave,
}: {
    settings: ConfigSettings
    saving: boolean
    saved: ConfigSaved | undefined
    refused: Error | null
    onSave: (changes: Record<string, ConfigValue>) => void
}) {
    const [drafts, setDrafts] = useState<ConfigDrafts>({})
    const form = configForm(settings.keys, drafts)
    const pending = Object.keys(form.changes).length
    const draft = (name: string, value: ConfigDrafts[string]) => setDrafts({ ...drafts, [name]: value })
    const perRepo = settings.keys.find((k) => k.name === 'capacity.slots_per_repo')?.value
    return (
        <form
            className="flex flex-col gap-6"
            aria-label="Limits and trust"
            data-testid="config-form"
            onSubmit={(event) => {
                event.preventDefault()
                onSave(form.changes)
            }}
        >
            <div className="grid items-start gap-6 xl:grid-cols-2">
                {groupedKeys(settings.keys).map(({ group, keys: shown }) => (
                    <Panel
                        key={group.title}
                        // Trust's lists of names want the width; the counts sit two panels to a row.
                        className={group.title === 'Trust' ? 'xl:col-span-2' : undefined}
                        data-testid={`config-group-${group.title.toLowerCase()}`}
                    >
                        <PanelHeader label={group.title} />
                        <p className="border-b px-3 py-2 text-xs text-muted-foreground">{group.blurb}</p>
                        <ul className="divide-y">
                            {shown.map(({ setting, label }) =>
                                setting.name === REPO_SLOTS ? (
                                    <RepoSlots
                                        key={setting.name}
                                        setting={setting}
                                        label={label}
                                        repos={settings.repos}
                                        perRepo={typeof perRepo === 'number' ? perRepo : null}
                                        draft={drafts[setting.name]}
                                        onDraft={(value) => draft(setting.name, value)}
                                    />
                                ) : (
                                    <li key={setting.name} className="flex items-center justify-between gap-4 p-3">
                                        <KeyLabel setting={setting} label={label} every={settings.every} />
                                        <Control
                                            setting={setting}
                                            draft={drafts[setting.name]}
                                            onDraft={(value) => draft(setting.name, value)}
                                        />
                                    </li>
                                ),
                            )}
                        </ul>
                    </Panel>
                ))}
            </div>
            {/* Kept in view at the page's foot, so a change made far down the page is never left unsaved unseen. */}
            <Panel className="sticky bottom-4 z-10 shadow-md" data-testid="config-save-bar">
                <div className="flex items-center justify-between gap-4 p-3">
                    <div className="flex min-w-0 flex-col gap-1">
                        <p className="text-sm text-foreground" data-testid="config-pending">
                            {pendingText(pending)}
                        </p>
                        <Notice
                            error={form.invalid.length > 0 ? `${form.invalid.join(', ')}: a whole number` : refused}
                        >
                            {saved ? savedText(saved) : null}
                        </Notice>
                    </div>
                    <span className="flex shrink-0 items-center gap-2">
                        <Button
                            type="button"
                            variant="ghost"
                            disabled={Object.keys(drafts).length === 0 || saving}
                            data-testid="config-discard"
                            onClick={() => setDrafts({})}
                        >
                            Discard
                        </Button>
                        <Button
                            type="submit"
                            disabled={pending === 0 || form.invalid.length > 0 || saving}
                            data-testid="config-save"
                        >
                            <Save />
                            Save
                        </Button>
                    </span>
                </div>
            </Panel>
        </form>
    )
}

/** A key in words, and under it its name in the file, where its value comes from, and how far the page may take it. */
function KeyLabel({ setting, label, every }: { setting: ConfigKey; label: string; every: number | null }) {
    return (
        <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-sm text-foreground">{label}</span>
            <span className="text-2xs text-muted-foreground">
                <code className="font-mono">{setting.name}</code>
                {' · '}
                {[sourceText(setting), boundText(setting)].filter(Boolean).join(' · ')}
                {setting.name === 'loop.interval_minutes' && every !== null
                    ? ` · --every ${every} sets the pace until the loop restarts`
                    : null}
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
    onDraft,
}: {
    setting: ConfigKey
    label: string
    repos: string[]
    perRepo: number | null
    draft: ConfigDrafts[string] | undefined
    onDraft: (value: ConfigDrafts[string]) => void
}) {
    const { name, value } = setting
    const counts = typeof value === 'object' && value !== null && !Array.isArray(value) ? value : {}
    const typed = typeof draft === 'object' && !Array.isArray(draft) ? draft : {}
    const [adding, setAdding] = useState('')
    const shown = [...new Set([...Object.keys(counts), ...Object.keys(typed)])].toSorted()
    const add = () => {
        const repo = adding.trim()
        if (repo !== '' && !shown.includes(repo)) {
            onDraft({ ...typed, [repo]: '' })
        }
        setAdding('')
    }
    const fallback = perRepo === null ? 'unmanaged' : String(perRepo)
    return (
        <li className="flex flex-col gap-2 p-3" data-testid="repo-slots">
            <KeyLabel setting={setting} label={label} every={null} />
            {shown.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                    no repository has its own count yet: each pool has the slots per repository ({fallback})
                </p>
            ) : (
                <ul className="flex flex-col gap-1">
                    {shown.map((repo) => (
                        <li key={repo} className="flex items-center justify-between gap-4">
                            <span className="font-mono text-xs text-foreground">{repo}</span>
                            <Count
                                name={`${name}.${repo}`}
                                text={typed[repo] ?? String(counts[repo] ?? '')}
                                placeholder={fallback}
                                onText={(text) => onDraft({ ...typed, [repo]: text })}
                            />
                        </li>
                    ))}
                </ul>
            )}
            <span className="flex items-center gap-2">
                <Input
                    list="repo-slots-repos"
                    aria-label="Repository to give its own count"
                    placeholder="another repository"
                    value={adding}
                    className="h-8 w-48 font-mono text-xs"
                    data-testid="repo-slots-add-name"
                    onChange={(event) => setAdding(event.currentTarget.value)}
                    onKeyDown={(event) => {
                        // Enter adds the row rather than saving the form.
                        if (event.key === 'Enter') {
                            event.preventDefault()
                            add()
                        }
                    }}
                />
                <datalist id="repo-slots-repos">
                    {repos
                        .filter((r) => !shown.includes(r))
                        .map((r) => (
                            <option key={r} value={r}>
                                {r}
                            </option>
                        ))}
                </datalist>
                <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    disabled={adding.trim() === ''}
                    data-testid="repo-slots-add"
                    onClick={add}
                >
                    <Plus />
                    Add
                </Button>
            </span>
        </li>
    )
}

/** The control for one key: a number field, a switch, or a list's entries to keep. */
function Control({
    setting,
    draft,
    onDraft,
}: {
    setting: ConfigKey
    draft: ConfigDrafts[string] | undefined
    onDraft: (value: ConfigDrafts[string]) => void
}) {
    const { name, value } = setting
    if (Array.isArray(value)) {
        const kept = Array.isArray(draft) ? draft : value
        if (value.length === 0) {
            return <span className="text-xs text-muted-foreground">none</span>
        }
        return (
            <fieldset aria-label={name} className="flex flex-wrap justify-end gap-3">
                {value.map((entry) => (
                    <label key={entry} className="inline-flex items-center gap-2 font-mono text-xs">
                        <Checkbox
                            checked={kept.includes(entry)}
                            data-testid={`${name}-${entry}`}
                            onCheckedChange={(checked) =>
                                onDraft(value.filter((e) => (e === entry ? checked === true : kept.includes(e))))
                            }
                        />
                        {entry}
                    </label>
                ))}
            </fieldset>
        )
    }
    if (name === STACKING) {
        const picked = typeof draft === 'string' ? draft : value
        return (
            <label htmlFor={name} className="inline-flex items-center gap-2 text-xs">
                <Checkbox
                    id={name}
                    checked={picked === 'never'}
                    disabled={value === 'never'}
                    data-testid={name}
                    onCheckedChange={(checked) =>
                        onDraft(checked === true || typeof value !== 'string' ? 'never' : value)
                    }
                />
                never
            </label>
        )
    }
    if (typeof value === 'boolean') {
        const strict = STRICTER_ON[name]
        return (
            <label htmlFor={name} className="inline-flex items-center gap-2 text-xs">
                <Checkbox
                    id={name}
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
            placeholder={value === null ? 'unmanaged' : ''}
            onText={onDraft}
        />
    )
}

/** A whole number's field, its value the text as typed: the form names one that is not a whole number. */
function Count({
    name,
    text,
    placeholder,
    onText,
}: {
    name: string
    text: string
    placeholder: string
    onText: (text: string) => void
}) {
    return (
        <Input
            aria-label={name}
            inputMode="numeric"
            value={text}
            placeholder={placeholder}
            className="readout h-8 w-24 text-right"
            data-testid={name}
            onChange={(event) => onText(event.currentTarget.value)}
        />
    )
}
