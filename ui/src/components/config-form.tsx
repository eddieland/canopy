import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { useState } from 'react'

import { saveConfig } from '@/api/mutations'
import { configQuery, keys } from '@/api/queries'
import type { ConfigKey, ConfigSaved, ConfigSettings, ConfigValue } from '@/api/types'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { boundText, configForm, REPO_SLOTS, savedText, sourceText } from '@/lib/config-settings'
import type { ConfigDrafts } from '@/lib/config-settings'

// The trust switches, and the side the page may move each to: the stricter one (TRUST_MODEL T8).
const STRICTER_ON: Record<string, boolean> = { 'trust.rebase': false, 'trust.commit_trailer': true }
const STACKING = 'policy.stacking'

/**
 * The limits and trust settings the loop reads from the user config, edited in place (DESIGN §22, M41): counts and
 * paces within the bounds the server sets, and trust settings only toward stricter. A save writes the user file alone,
 * keeping its comments, then asks the loop to read it again as Reload does.
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
    return (
        <Panel data-testid="config-form">
            <PanelHeader label="Limits and trust" />
            {data === undefined ? (
                <div className="min-h-72">
                    {error ? <Notice error={error} className="p-3" /> : <PanelSkeleton rows={6} />}
                </div>
            ) : (
                <Form
                    key={data.hash}
                    settings={data}
                    saving={mutation.isPending}
                    saved={mutation.data}
                    refused={mutation.error}
                    onSave={(changes) => mutation.mutate({ hash: data.hash, changes })}
                />
            )}
        </Panel>
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
    const changed = Object.keys(form.changes).length > 0
    const draft = (name: string, value: ConfigDrafts[string]) => setDrafts({ ...drafts, [name]: value })
    const perRepo = settings.keys.find((k) => k.name === 'capacity.slots_per_repo')?.value
    return (
        <form
            onSubmit={(event) => {
                event.preventDefault()
                onSave(form.changes)
            }}
        >
            <ul className="divide-y">
                {settings.keys.map((key) => (
                    <li key={key.name} className="flex items-center justify-between gap-4 p-3">
                        <div className="flex min-w-0 flex-col gap-0.5">
                            <span className="font-mono text-xs text-foreground">{key.name}</span>
                            <span className="text-2xs text-muted-foreground">
                                {[sourceText(key), boundText(key)].filter(Boolean).join(' · ')}
                                {key.name === 'loop.interval_minutes' && settings.every !== null
                                    ? ` · --every ${settings.every} sets the pace until the loop restarts`
                                    : null}
                            </span>
                        </div>
                        <Control
                            setting={key}
                            repos={settings.repos}
                            perRepo={typeof perRepo === 'number' ? perRepo : null}
                            draft={drafts[key.name]}
                            onDraft={(value) => draft(key.name, value)}
                        />
                    </li>
                ))}
            </ul>
            <div className="flex items-center justify-between gap-4 border-t p-3">
                <div className="flex flex-col gap-1">
                    <p className="text-sm text-muted-foreground">
                        Saved to <code className="font-mono text-xs">{settings.user_file}</code> with its comments kept;
                        the workspace file is never written. Anything else, or looser than this allows, is the
                        file&apos;s to change.
                    </p>
                    <Notice error={form.invalid.length > 0 ? `${form.invalid.join(', ')}: a whole number` : refused}>
                        {saved ? savedText(saved) : null}
                    </Notice>
                </div>
                <Button
                    type="submit"
                    variant="outline"
                    disabled={!changed || form.invalid.length > 0 || saving}
                    data-testid="config-save"
                >
                    <Save />
                    Save
                </Button>
            </div>
        </form>
    )
}

/** The control for one key: a number field, one per repository, a switch, or a list's entries to keep. */
function Control({
    setting,
    repos,
    perRepo,
    draft,
    onDraft,
}: {
    setting: ConfigKey
    repos: string[]
    perRepo: number | null
    draft: ConfigDrafts[string] | undefined
    onDraft: (value: ConfigDrafts[string]) => void
}) {
    const { name, value } = setting
    if (name === REPO_SLOTS) {
        const counts = typeof value === 'object' && value !== null && !Array.isArray(value) ? value : {}
        const typed = typeof draft === 'object' && !Array.isArray(draft) ? draft : {}
        const names = [...new Set([...repos, ...Object.keys(counts)])].toSorted()
        return (
            <span className="flex flex-wrap justify-end gap-3">
                {names.map((repo) => (
                    <label key={repo} className="inline-flex items-center gap-2 text-xs">
                        {repo}
                        <Count
                            name={`${name}.${repo}`}
                            text={typed[repo] ?? String(counts[repo] ?? '')}
                            placeholder={perRepo === null ? 'unmanaged' : String(perRepo)}
                            onText={(text) => onDraft({ ...typed, [repo]: text })}
                        />
                    </label>
                ))}
            </span>
        )
    }
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
