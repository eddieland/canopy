import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useBlocker } from '@tanstack/react-router'
import { FilePlus, History, Save, Trash2, Undo2, X } from 'lucide-react'
import { useState } from 'react'

import { deleteInstructions, saveInstructions } from '@/api/mutations'
import { instructionsVersionsQuery, keys } from '@/api/queries'
import type { AgentInstructions, InstructionsAgent, InstructionsList, InstructionsVersion } from '@/api/types'
import { Age } from '@/components/age'
import { Code } from '@/components/code'
import { ConfirmLeave } from '@/components/confirm-leave'
import { CopyButton } from '@/components/copy-button'
import { Disclosure } from '@/components/disclosure'
import { MarkdownField } from '@/components/markdown-field'
import { Notice } from '@/components/notice'
import { Panel, PanelFooter, PanelHeader } from '@/components/panel'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { useFirstInView } from '@/hooks/use-first-in-view'
import { fileName, instructionsState, READERS, savedBytes, unsavedClause } from '@/lib/instructions'
import type { InstructionsReader, InstructionsState } from '@/lib/instructions'
import { cn } from '@/lib/utils'

/** What the operator has written and not saved, by agent: none for an agent whose field holds its file's text. */
type Drafts = Partial<Record<InstructionsAgent, string>>

// The accent hairline at the start of what holds an unsaved change, as a config page's changed row wears it.
const CHANGED = 'relative before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-accent'

// Each state's chip in its panel's header, or none for a file a run reads as it is.
const STATE_CHIP: Record<InstructionsState, { tone: 'plain' | 'failed'; meaning: string } | null> = {
    none: { tone: 'plain', meaning: 'no file: its runs read none until you create one' },
    missing: { tone: 'failed', meaning: 'its key names a file that is not there: every run of it is refused' },
    refused: { tone: 'failed', meaning: 'a run of it would refuse the file, and so every run of it is refused' },
    set: null,
}

/**
 * Every agent's standing instructions file (DESIGN §12), each in a panel of its own: where it is, why a run would
 * refuse it, and its text in the Markdown editor, saved from its panel's foot over the version the page read. An index
 * of the agents sits beside them, marking the one in view and each with an edit not saved; each panel is its agent's
 * anchor (`#worker`). Leaving with an edit not saved asks first. An agent with no file creates its default, and a
 * default can be deleted; a file a key names is only edited, and the page never chooses which file (TRUST_MODEL T8).
 * Each panel lists its kept versions on demand, and restores one into its editor.
 */
export function InstructionsForm({ list }: { list: InstructionsList }) {
    const [drafts, setDrafts] = useState<Drafts>({})
    const inView = useFirstInView(READERS.map((r) => r.agent).join(' '))
    const unsaved = READERS.filter((r) => drafts[r.agent] !== undefined)
    const leaving = useBlocker({
        shouldBlockFn: ({ current, next }) => current.pathname !== next.pathname,
        enableBeforeUnload: true,
        disabled: unsaved.length === 0,
        withResolver: true,
    })

    function draft(of: InstructionsAgent, text: string | undefined) {
        setDrafts((was) => {
            const next = { ...was }
            if (text === undefined) {
                delete next[of]
            } else {
                next[of] = text
            }
            return next
        })
    }

    return (
        <div className="@container">
            {/* Two columns once the pane has room for the index beside the files, as a config page's: Tailwind's `6xl`.
                Written out, so Tailwind finds them. */}
            <div className="grid grid-cols-1 gap-x-8 gap-y-6 @6xl:grid-cols-[12rem_minmax(0,56rem)]">
                <nav
                    aria-label="Agents"
                    className={cn(
                        'flex flex-wrap gap-x-4 gap-y-1',
                        '@6xl:sticky @6xl:top-0 @6xl:flex-col @6xl:self-start',
                    )}
                    data-testid="instructions-index"
                >
                    {READERS.map((reader) => (
                        <Link
                            key={reader.agent}
                            to="/settings/instructions"
                            hash={reader.agent}
                            // Only the agent the address names is the link to where you are, not all four.
                            activeOptions={{ includeHash: true }}
                            data-current={inView === reader.agent || undefined}
                            className={cn(
                                'flex items-baseline gap-2 py-0.5 text-sm text-muted-foreground hover:text-foreground',
                                'data-current:text-foreground',
                            )}
                        >
                            <span className={cn(inView === reader.agent && 'font-medium')}>{reader.label}</span>
                            <IndexState file={list.files.find((f) => f.agent === reader.agent)} />
                            {drafts[reader.agent] !== undefined && (
                                <span className="readout text-2xs text-accent">unsaved</span>
                            )}
                        </Link>
                    ))}
                </nav>
                <div className="flex max-w-4xl min-w-0 flex-col gap-6">
                    {READERS.map((reader) => {
                        const file = list.files.find((f) => f.agent === reader.agent)
                        return file === undefined ? null : (
                            <InstructionsFile
                                key={reader.agent}
                                reader={reader}
                                file={file}
                                maxBytes={list.max_bytes}
                                draft={drafts[reader.agent]}
                                onDraft={(text) => draft(reader.agent, text)}
                            />
                        )
                    })}
                </div>
            </div>
            <ConfirmLeave
                open={leaving.status === 'blocked'}
                lost={[unsavedClause(unsaved.map((r) => r.label))]}
                onStay={() => leaving.reset?.()}
                onLeave={() => leaving.proceed?.()}
            />
        </div>
    )
}

/** An index entry's word for a file a run cannot read as it is, or for none at all; nothing for one it reads. */
function IndexState({ file }: { file: AgentInstructions | undefined }) {
    const state = file === undefined ? 'none' : instructionsState(file)
    if (state === 'set') {
        return null
    }
    return (
        <span className={cn('readout text-2xs', state === 'none' ? 'text-muted-foreground' : 'text-status-failed')}>
            {state}
        </span>
    )
}

/**
 * One agent's file in its panel: which runs read it and where it is, why a run would refuse it, then its text in the
 * editor, and in the panel's foot Save and Revert, what a save writes, what the text costs against the bound, Delete
 * for a default, then what a change did. An agent with no file says so and offers Create, which opens an empty editor;
 * one whose file cannot be shown says why. Under it, its kept versions, read when opened.
 */
function InstructionsFile({
    reader,
    file,
    maxBytes,
    draft,
    onDraft,
}: {
    reader: InstructionsReader
    file: AgentInstructions
    maxBytes: number
    draft: string | undefined
    onDraft: (text: string | undefined) => void
}) {
    const client = useQueryClient()
    const [creating, setCreating] = useState(false)
    const [confirming, setConfirming] = useState(false)
    const saved = file.text ?? ''
    const text = draft ?? saved
    const bytes = savedBytes(text)
    const over = bytes > maxBytes
    const state = instructionsState(file)
    const chip = STATE_CHIP[state]
    const name = fileName(file.path)

    function changed(written: AgentInstructions) {
        client.setQueryData<InstructionsList>(keys.instructions, (was) =>
            was === undefined
                ? was
                : { ...was, files: was.files.map((f) => (f.agent === written.agent ? written : f)) },
        )
        void client.invalidateQueries({ queryKey: keys.instructionsVersions(written.agent) })
        onDraft(undefined)
        setCreating(false)
        setConfirming(false)
    }

    // One mutation for both, so what it says, and any refusal, is always the latest change's.
    const change = useMutation({
        mutationFn: (kind: 'save' | 'delete') =>
            kind === 'save'
                ? saveInstructions(file.agent, text, file.sha256)
                : deleteInstructions(file.agent, file.sha256 ?? ''),
        onSuccess: changed,
    })
    const pending = change.isPending
    // A default not there shows no editor until Create, or a restored version, opens one.
    const editing = (file.text !== null || file.missing) && (state !== 'none' || creating || draft !== undefined)
    const outcome = change.isSuccess
        ? change.variables === 'save'
            ? `Saved ${name}: runs started from now read it.`
            : `Deleted ${name}: runs started from now read none.`
        : null
    return (
        <Panel
            id={reader.agent}
            className={cn('scroll-mt-4', draft !== undefined && CHANGED)}
            aria-label={`${reader.label} instructions`}
            data-testid={`instructions-${file.agent}`}
            data-changed={draft !== undefined || undefined}
        >
            <PanelHeader label={reader.label}>
                {chip !== null && <Chip tone={chip.tone} word={state} meaning={chip.meaning} />}
            </PanelHeader>
            <div className="flex flex-col gap-2 p-3">
                <p className="text-sm text-muted-foreground">
                    Read by {reader.reaches}.{state === 'none' && !editing && <> None yet, so they hear nothing.</>}
                </p>
                {/* Where the file is, on a line of its own, and whether its key names it or it is the default. */}
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                    <span className="inline-flex min-w-0 items-center gap-1" data-testid="instructions-path">
                        <Code className="break-all">{file.path}</Code>
                        <CopyButton text={file.path} label={`${reader.label.toLowerCase()} instructions path`} />
                    </span>
                    <span>
                        {file.source === 'config' ? (
                            <>
                                named by <Code>{file.key}</Code>
                            </>
                        ) : (
                            'its default, in your instructions folder'
                        )}
                    </span>
                </p>
                {file.problem !== null && (
                    <p className="text-sm text-status-failed" data-testid="instructions-problem">
                        {file.problem}
                    </p>
                )}
                {editing && (
                    <MarkdownField
                        value={text}
                        onValueChange={(value) => onDraft(value === saved ? undefined : value)}
                        size="tall"
                        aria-label={`${reader.label} standing instructions`}
                    />
                )}
            </div>
            {editing ? (
                <PanelFooter>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button onClick={() => change.mutate('save')} disabled={draft === undefined || over || pending}>
                            <Save />
                            Save
                        </Button>
                        {state === 'none' ? (
                            <Button
                                variant="outline"
                                onClick={() => {
                                    onDraft(undefined)
                                    setCreating(false)
                                }}
                                disabled={pending}
                            >
                                <X />
                                Cancel
                            </Button>
                        ) : (
                            <Button
                                variant="outline"
                                onClick={() => onDraft(undefined)}
                                disabled={draft === undefined || pending}
                            >
                                <Undo2 />
                                Revert
                            </Button>
                        )}
                        <span
                            className={cn(
                                'ml-auto readout text-xs',
                                over ? 'text-status-failed' : 'text-muted-foreground',
                            )}
                            data-testid="instructions-bytes"
                        >
                            {bytes.toLocaleString()} of {maxBytes.toLocaleString()} bytes
                            {over && ': a run would refuse it'}
                        </span>
                        {file.source === 'default' && !file.missing && !confirming && (
                            // The quietest of the row, at its end, as a forget is: the loudest button is clicked first.
                            <Button
                                variant="ghost"
                                className="text-status-failed"
                                onClick={() => setConfirming(true)}
                                disabled={pending}
                            >
                                <Trash2 />
                                Delete
                            </Button>
                        )}
                    </div>
                    {confirming ? (
                        <fieldset
                            aria-label={`Delete ${name}?`}
                            className="flex flex-wrap items-center gap-2 text-xs text-status-failed"
                        >
                            <span>Delete {name}? Its runs then hear nothing; its text is kept among the versions.</span>
                            <Button
                                variant="destructive"
                                size="sm"
                                onClick={() => change.mutate('delete')}
                                disabled={pending}
                            >
                                Delete
                            </Button>
                            <Button variant="outline" size="sm" onClick={() => setConfirming(false)} disabled={pending}>
                                Keep it
                            </Button>
                        </fieldset>
                    ) : (
                        <p className="text-xs text-muted-foreground">{saveText(name, file.missing)}</p>
                    )}
                    <Notice error={change.error}>{draft === undefined ? outcome : null}</Notice>
                </PanelFooter>
            ) : (
                state === 'none' && (
                    <PanelFooter>
                        <div className="flex flex-wrap items-center gap-2">
                            <Button variant="outline" onClick={() => setCreating(true)}>
                                <FilePlus />
                                Create
                            </Button>
                        </div>
                        <Notice error={change.error}>{outcome}</Notice>
                    </PanelFooter>
                )
            )}
            {file.versions > 0 && (
                <Versions
                    agent={file.agent}
                    count={file.versions}
                    onRestore={(version) => onDraft(version === saved ? undefined : version)}
                />
            )}
        </Panel>
    )
}

/**
 * An agent's kept versions, under a disclosure, read when it opens: each the file as it was before an edit or a
 * delete, when, its size, its text on Show, and Restore, which puts that text in the editor as an edit to save.
 */
function Versions({
    agent,
    count,
    onRestore,
}: {
    agent: InstructionsAgent
    count: number
    onRestore: (text: string) => void
}) {
    const [open, setOpen] = useState(false)
    const read = useQuery({ ...instructionsVersionsQuery(agent), enabled: open })
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <div className="border-t px-3 py-1.5">
                <Disclosure
                    open={open}
                    what={`versions (${count})`}
                    of={agent}
                    className="-ml-2"
                    data-testid="instructions-versions"
                />
                <CollapsibleContent className="pb-1.5">
                    {read.isPending && <p className="text-xs text-muted-foreground">Reading the versions…</p>}
                    <Notice error={read.error} />
                    {read.data !== undefined && (
                        <ul className="divide-y" aria-label={`Versions of the ${agent} instructions`}>
                            {read.data.versions.map((version) => (
                                <VersionRow key={version.id} version={version} onRestore={onRestore} />
                            ))}
                        </ul>
                    )}
                    {read.data !== undefined && (
                        <p className="pt-1 text-xs text-muted-foreground">
                            The last {read.data.keep} are kept; a change past them drops the oldest.
                        </p>
                    )}
                </CollapsibleContent>
            </div>
        </Collapsible>
    )
}

/** One kept version: when, before what, its size, then Show for its text and Restore into the editor. */
function VersionRow({ version, onRestore }: { version: InstructionsVersion; onRestore: (text: string) => void }) {
    const [shown, setShown] = useState(false)
    const { text } = version
    return (
        <li className="flex flex-col gap-1.5 py-1.5" data-testid="instructions-version">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <History aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="text-sm">
                    Before {version.kind === 'delete' ? 'a delete' : 'an edit'}, <Age variant="ago" at={version.at} />
                </span>
                <span className="readout text-xs text-muted-foreground">{version.size.toLocaleString()} bytes</span>
                <span className="ml-auto flex items-center gap-1">
                    <Button variant="ghost" size="xs" onClick={() => setShown(!shown)} disabled={text === null}>
                        {shown ? 'Hide' : 'Show'}
                    </Button>
                    <Button
                        variant="outline"
                        size="xs"
                        onClick={() => {
                            if (text !== null) {
                                onRestore(text)
                            }
                        }}
                        disabled={text === null}
                        title="Puts this text in the editor, to save as any edit"
                    >
                        Restore
                    </Button>
                </span>
            </div>
            {shown && text !== null && (
                <pre
                    className={cn(
                        'max-h-60 overflow-auto rounded-sm bg-surface-raised p-2',
                        'font-mono text-xs whitespace-pre-wrap',
                    )}
                >
                    {text}
                </pre>
            )}
        </li>
    )
}

// What Save will do, the line under it: write the file, keeping the one there as a version, or make it.
function saveText(name: string, missing: boolean): string {
    return missing
        ? `Save makes ${name}, readable by you alone.`
        : `Save writes ${name}, keeping the file as it was among its versions.`
}
