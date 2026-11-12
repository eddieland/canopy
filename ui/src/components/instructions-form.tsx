import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useBlocker } from '@tanstack/react-router'
import { Save, Undo2 } from 'lucide-react'
import { useState } from 'react'

import { saveInstructions } from '@/api/mutations'
import { keys } from '@/api/queries'
import type { AgentInstructions, InstructionsAgent, InstructionsList } from '@/api/types'
import { Code } from '@/components/code'
import { ConfirmLeave } from '@/components/confirm-leave'
import { CopyButton } from '@/components/copy-button'
import { MarkdownField } from '@/components/markdown-field'
import { Notice } from '@/components/notice'
import { Panel, PanelFooter, PanelHeader } from '@/components/panel'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
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
    none: { tone: 'plain', meaning: 'the config names no file, so its runs read none' },
    missing: { tone: 'failed', meaning: 'the config names a file that is not there: every run of it is refused' },
    refused: { tone: 'failed', meaning: 'a run of it would refuse the file, and so every run of it is refused' },
    set: null,
}

/**
 * Every agent's standing instructions file (DESIGN §12), each in a panel of its own: where it is, why a run would
 * refuse it, and its text in the Markdown editor, saved from its panel's foot over the version the page read. An index
 * of the agents sits beside them, marking the one in view and each with an edit not saved; each panel is its agent's
 * anchor (`#worker`). Leaving with an edit not saved asks first. Only a file the config names is written, never which
 * file (TRUST_MODEL T8).
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
 * editor, and in the panel's foot Save and Revert, what a save writes and what the text costs against the bound, then
 * what a save did. An agent whose key names no file says so, with no editor; one whose file cannot be shown says why.
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
    const saved = file.text ?? ''
    const text = draft ?? saved
    const bytes = savedBytes(text)
    const over = bytes > maxBytes
    const mutation = useMutation({
        mutationFn: () => saveInstructions(file.agent, text, file.sha256),
        onSuccess: (written) => {
            client.setQueryData<InstructionsList>(keys.instructions, (was) =>
                was === undefined
                    ? was
                    : { ...was, files: was.files.map((f) => (f.agent === written.agent ? written : f)) },
            )
            onDraft(undefined)
        },
    })
    const state = instructionsState(file)
    const chip = STATE_CHIP[state]
    const editable = file.path !== null && (file.text !== null || file.missing)
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
                    Read by {reader.reaches}.{' '}
                    {file.path === null ? (
                        <>
                            <Code>{file.key}</Code> names no file, so none of them hears any. Name one in your{' '}
                            <Code>config.toml</Code> and Reload, on Settings, to write it here.
                        </>
                    ) : (
                        <span className="inline-flex items-center gap-1" data-testid="instructions-path">
                            <Code>{file.path}</Code>
                            <CopyButton text={file.path} label={`${reader.label.toLowerCase()} instructions path`} />
                        </span>
                    )}
                </p>
                {file.problem !== null && (
                    <p className="text-sm text-status-failed" data-testid="instructions-problem">
                        {file.problem}
                    </p>
                )}
                {editable && (
                    <MarkdownField
                        value={text}
                        onValueChange={(value) => onDraft(value === saved ? undefined : value)}
                        size="tall"
                        aria-label={`${reader.label} standing instructions`}
                    />
                )}
            </div>
            {editable && file.path !== null && (
                <PanelFooter>
                    <div className="flex flex-wrap items-center gap-2">
                        <Button
                            onClick={() => mutation.mutate()}
                            disabled={draft === undefined || over || mutation.isPending}
                        >
                            <Save />
                            Save
                        </Button>
                        <Button
                            variant="outline"
                            onClick={() => onDraft(undefined)}
                            disabled={draft === undefined || mutation.isPending}
                        >
                            <Undo2 />
                            Revert
                        </Button>
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
                    </div>
                    <p className="text-xs text-muted-foreground">{saveText(file.path, file.missing)}</p>
                    <Notice error={mutation.error}>
                        {mutation.isSuccess && draft === undefined
                            ? `Saved ${fileName(file.path)}: runs started from now read it.`
                            : null}
                    </Notice>
                </PanelFooter>
            )}
        </Panel>
    )
}

// What Save will do, the line under it: write the file, keeping the one there, or make the one the config names.
function saveText(path: string, missing: boolean): string {
    const name = fileName(path)
    return missing
        ? `Save makes ${name}, readable by you alone.`
        : `Save writes ${name}, keeping the file as it was as ${name}.bak.`
}
