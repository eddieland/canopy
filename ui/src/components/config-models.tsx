import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { configModelsQuery, modelOverridesQuery, modelsQuery } from '@/api/queries'
import type { ChoreModel, ConfigModels as Models, ConfiguredModel, ModelOverride } from '@/api/types'
import { Disclosure } from '@/components/disclosure'
import { Field, Fields } from '@/components/fields'
import { None } from '@/components/none'
import { Notice } from '@/components/notice'
import { PanelLoading } from '@/components/panel'
import { Chip } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { RUNTIME_DEFAULT } from '@/lib/models'
import { readFailure } from '@/lib/read-failure'

/**
 * The model config chooses for each of canopy's agents and each chore (DESIGN §13, §19), read only: a row each, its
 * model and the variant it runs at, or `runtime default`, then a muted line naming the file to edit, and the
 * runtime's own list of models, read only when opened, since each read starts the runtime. The models are the ones
 * the loop runs on, so an edit shows here after Reload. A ticket's override is set on its own page, and listed here,
 * since it outlasts `canopy forget` and spends until it is cleared.
 */
export function ConfigModels() {
    const query = useQuery(configModelsQuery)
    if (query.data === undefined) {
        return <PanelLoading query={query} rows={4} className="min-h-40" />
    }
    const { agents, chores } = query.data
    return (
        <div data-testid="config-models">
            {/* Wider than a detail page's labels: a chore's, `chore:memory-tickets`, holds on one line. */}
            <Fields className="grid-cols-[12rem_minmax(0,1fr)]">
                {agents.map((row) => (
                    <Field key={row.agent} label={<Key>{row.agent}</Key>} data-testid="config-model">
                        <ModelValue row={row} />
                    </Field>
                ))}
                {chores.map((row) => (
                    <Field key={row.chore} label={<Key>{`chore:${row.chore}`}</Key>} data-testid="config-model">
                        <ChoreValue row={row} />
                    </Field>
                ))}
            </Fields>
            <p className="max-w-3xl px-3 pb-3 text-xs text-muted-foreground" data-testid="config-models-where">
                <WhereToEdit models={query.data} />
            </p>
            <Overrides />
            <RuntimeModels />
        </div>
    )
}

/**
 * A row's label as the operator types it in TOML, `chore:build-health`, in the label's type but never uppercased, since
 * it is an id.
 */
function Key({ children }: { children: ReactNode }) {
    return <span className="normal-case">{children}</span>
}

/** One of canopy's agents' model: `[runtime.models]`'s, or the runtime's default. */
function ModelValue({ row }: { row: ConfiguredModel }) {
    return (
        <span className="flex flex-wrap items-baseline gap-x-2">
            <Model model={row.model} variant={row.variant} />
            {row.agent === 'chore' && row.model !== null && (
                <span className="text-xs text-muted-foreground">every chore without a model of its own</span>
            )}
        </span>
    )
}

/**
 * One chore's model: its own, `runtime.models.chore`, or the runtime's default; or, for a chore whose command runs an
 * agent of the operator's own, that agent's, which its own definition chooses and config never sets.
 */
function ChoreValue({ row }: { row: ChoreModel }) {
    if (row.source === 'agent') {
        return (
            <span className="text-xs text-muted-foreground">
                {row.agent === null ? 'an agent of yours' : <Code>{row.agent}</Code>}, which chooses its own model in
                its definition
            </span>
        )
    }
    return (
        <span className="flex flex-wrap items-baseline gap-x-2">
            <Model model={row.model} variant={row.variant} />
            {row.source === 'chore' && <Chip>own model</Chip>}
        </span>
    )
}

/**
 * A model and its variant, `provider/model@variant` in monospace, the variant muted, or `runtime default` in muted
 * sans when there is none, since it is no id.
 */
function Model({ model, variant }: { model: string | null; variant: string | null }) {
    if (model === null) {
        return <span className="text-xs text-muted-foreground">{RUNTIME_DEFAULT}</span>
    }
    return (
        <span className="font-mono text-xs break-all">
            {model}
            {variant !== null && <span className="text-muted-foreground">@{variant}</span>}
        </span>
    )
}

/**
 * Every ticket with a model the operator chose for one of its agents, each linking to its ticket, or `none`: an
 * override outlasts `canopy forget` and spends until it is cleared, so a canary left on a costly model shows here.
 */
function Overrides() {
    const query = useQuery(modelOverridesQuery)
    return (
        <section className="border-t px-3 py-2" aria-labelledby="model-overrides">
            <h3 id="model-overrides" className="panel-label">
                Tickets with an override
            </h3>
            {query.data === undefined ? (
                <PanelLoading query={query} rows={1} />
            ) : (
                <OverrideList overrides={query.data} />
            )}
        </section>
    )
}

function OverrideList({ overrides }: { overrides: readonly ModelOverride[] }) {
    if (overrides.length === 0) {
        return <None className="text-xs" />
    }
    return (
        <ul className="flex flex-col gap-0.5 pt-1" aria-label="Tickets with an override">
            {overrides.map((o) => (
                <li key={`${o.ticket} ${o.agent}`} className="flex flex-wrap items-baseline gap-x-2">
                    <TicketLink ticketKey={o.ticket} />
                    <span className="text-xs text-muted-foreground">{o.agent}</span>
                    <Model model={o.model} variant={o.variant ?? null} />
                </li>
            ))}
        </ul>
    )
}

/**
 * Where to change them: the file `[runtime.models]` is in and the file the chores are, or, while nothing sets one,
 * the two files that may: the user file, for every workspace, or this workspace's private file. Never the workspace
 * file, which may not choose a model (TRUST_MODEL T7).
 */
function WhereToEdit({ models }: { models: Models }) {
    const { models_file: modelsFile, chores_file: choresFile } = models
    const chores =
        choresFile !== null && choresFile !== modelsFile ? (
            <>
                {' '}
                A chore&apos;s <Code>model</Code> is in its <Code>[chores.NAME]</Code> table, in{' '}
                <FilePath path={choresFile} />.
            </>
        ) : null
    if (modelsFile === null) {
        const user = <FilePath path={models.user_file} />
        const own = <FilePath path={models.private_file} />
        const add = (
            <>
                Add it to {user} for every workspace, or to {own} for this one alone.
            </>
        )
        return (
            <>
                Read only. Nothing sets <Code>[runtime.models]</Code> yet. {add}
                {chores} Reload, below, reads them again.
            </>
        )
    }
    const together =
        choresFile === modelsFile ? (
            <>
                , and a chore&apos;s <Code>model</Code> in its table there
            </>
        ) : null
    return (
        <>
            Read only. Edit <Code>[runtime.models]</Code> in <FilePath path={modelsFile} />
            {together}.{chores} Reload, below, reads them again.
        </>
    )
}

/** A config file's path. Its own test id, so a screenshot hides the mock's, which is in a temporary directory. */
function FilePath({ path }: { path: string }) {
    return (
        <code className="font-mono text-xs break-all" data-testid="config-models-file">
            {path}
        </code>
    )
}

function Code({ children }: { children: ReactNode }) {
    return <code className="font-mono text-xs">{children}</code>
}

/** A listed model's variants, each as it is named after the model, `@high`, inline and muted; nothing for none. */
function Variants({ variants }: { variants: readonly string[] }) {
    if (variants.length === 0) {
        return null
    }
    return <span className="text-muted-foreground"> {variants.map((v) => `@${v}`).join(' ')}</span>
}

/**
 * The models the runtime lists, as `canopy models` prints them, each with its variants: read when opened, since a read
 * can start it, or found already read by a ticket's page, as its model menus share the list.
 */
function RuntimeModels() {
    const [open, setOpen] = useState(false)
    const listed = useQuery({ ...modelsQuery, enabled: open })
    const models = listed.data?.models ?? []
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <div className="border-t px-3 py-1.5">
                <Disclosure open={open} what="the runtime's models" className="-ml-2" data-testid="runtime-models" />
                <CollapsibleContent className="pb-1.5">
                    {listed.isPending && (
                        <p className="text-xs text-muted-foreground">Reading the runtime&apos;s models…</p>
                    )}
                    {/* A read that failed did nothing, so it says so in a read's words, as the model picker does. */}
                    <Notice error={listed.data?.error ?? (listed.isError ? readFailure(listed.error) : null)} />
                    {models.length > 0 && (
                        <ul className="flex flex-col gap-0.5 font-mono text-xs" aria-label="The runtime's models">
                            {models.map((model) => (
                                <li key={model} className="break-all">
                                    {model}
                                    <Variants variants={listed.data?.variants[model] ?? []} />
                                </li>
                            ))}
                        </ul>
                    )}
                </CollapsibleContent>
            </div>
        </Collapsible>
    )
}
