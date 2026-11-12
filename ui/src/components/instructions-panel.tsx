import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCw, Save, Undo2 } from 'lucide-react'
import { useState } from 'react'

import { saveInstructions } from '@/api/mutations'
import { instructionsQuery, keys } from '@/api/queries'
import type { AgentInstructions, InstructionsAgent, InstructionsList } from '@/api/types'
import { Code } from '@/components/code'
import { CopyButton } from '@/components/copy-button'
import { MarkdownField } from '@/components/markdown-field'
import { Notice } from '@/components/notice'
import { Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { READERS, savedBytes } from '@/lib/instructions'
import type { InstructionsReader } from '@/lib/instructions'
import { cn } from '@/lib/utils'

/** What the operator has written and not saved, by agent: none for an agent whose field holds its file's text. */
type Drafts = Partial<Record<InstructionsAgent, string>>

/**
 * The operator's standing instructions to each agent (DESIGN §12), as the files `paths.*_instructions` name: one agent
 * at a time, picked above, its file in the Markdown editor, saved over the version the page read. An agent picked away
 * from keeps what was written for it, marked unsaved on its pick, so moving between them loses nothing. Only a file
 * the config names is written, never which file (TRUST_MODEL T8).
 */
export function InstructionsPanel() {
    const query = useQuery(instructionsQuery)
    const [agent, setAgent] = useState<InstructionsAgent>('worker')
    const [drafts, setDrafts] = useState<Drafts>({})
    const { data } = query

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
        <Panel>
            <PanelHeader label="Standing instructions">
                <ToggleGroup
                    type="single"
                    value={agent}
                    onValueChange={(value) => {
                        const picked = READERS.find((r) => r.agent === value)
                        if (picked !== undefined) {
                            setAgent(picked.agent)
                        }
                    }}
                    aria-label="Agent"
                    data-testid="instructions-agent"
                >
                    {READERS.map((reader) => (
                        <ToggleGroupItem key={reader.agent} value={reader.agent}>
                            {reader.label}
                            {drafts[reader.agent] !== undefined && (
                                <>
                                    <span className="size-1.5 rounded-full bg-primary" aria-hidden />
                                    <span className="sr-only"> unsaved</span>
                                </>
                            )}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </PanelHeader>
            <p className="max-w-3xl px-3 pt-3 text-sm text-muted-foreground">
                What every run of an agent hears from you, after its prompt&apos;s own obligations, which come first.
                Each file is yours, named by <Code>paths.*_instructions</Code> in your config; a save writes the text
                and keeps the file as it was as <Code>.bak</Code> beside it. Every run started after a save reads it; a
                run already going keeps the prompt it has.
            </p>
            {data === undefined ? (
                <PanelLoading query={query} rows={4} className="min-h-60" />
            ) : (
                READERS.map((reader) => {
                    const file = data.files.find((f) => f.agent === reader.agent)
                    return file === undefined ? null : (
                        <InstructionsFile
                            key={reader.agent}
                            reader={reader}
                            file={file}
                            maxBytes={data.max_bytes}
                            draft={drafts[reader.agent]}
                            onDraft={(text) => draft(reader.agent, text)}
                            hidden={reader.agent !== agent}
                            readAgain={() => void query.refetch()}
                            reading={query.isFetching}
                        />
                    )
                })
            )}
        </Panel>
    )
}

/**
 * One agent's file: where it is, why a run would refuse it, and the editor over its text, with what it costs in bytes
 * against the bound a run takes. Kept mounted while another agent is shown, so its editor's undo stays too.
 */
function InstructionsFile({
    reader,
    file,
    maxBytes,
    draft,
    onDraft,
    hidden,
    readAgain,
    reading,
}: {
    reader: InstructionsReader
    file: AgentInstructions
    maxBytes: number
    draft: string | undefined
    onDraft: (text: string | undefined) => void
    hidden: boolean
    readAgain: () => void
    reading: boolean
}) {
    const client = useQueryClient()
    const saved = file.text ?? ''
    const text = draft ?? saved
    const bytes = savedBytes(text)
    const over = bytes > maxBytes
    const mutation = useMutation({
        mutationFn: () => saveInstructions(file.agent, text, file.sha256 ?? null),
        onSuccess: (written) => {
            client.setQueryData<InstructionsList>(keys.instructions, (was) =>
                was === undefined
                    ? was
                    : { ...was, files: was.files.map((f) => (f.agent === written.agent ? written : f)) },
            )
            onDraft(undefined)
        },
    })
    const editable = file.path !== null && (file.text !== null || file.missing)
    return (
        <div className="flex flex-col gap-2 p-3" hidden={hidden} data-testid={`instructions-${file.agent}`}>
            <p className="text-sm text-muted-foreground">
                Read by {reader.reaches}.{' '}
                {file.path === null ? (
                    <>
                        <Code>{file.key}</Code> names no file, so none of them hears any. Name one in your{' '}
                        <Code>config.toml</Code> and Reload to write it here.
                    </>
                ) : (
                    <span className="inline-flex items-center gap-1" data-testid="instructions-path">
                        <Code>{file.path}</Code>
                        <CopyButton text={file.path} label={`${reader.label.toLowerCase()} instructions path`} />
                    </span>
                )}
            </p>
            {file.problem !== null && (
                <p className="text-sm text-status-blocked" data-testid="instructions-problem">
                    {file.problem}
                </p>
            )}
            {editable && (
                <>
                    <MarkdownField
                        value={text}
                        onValueChange={(value) => onDraft(value === saved ? undefined : value)}
                        size="tall"
                        aria-label={`${reader.label} standing instructions`}
                    />
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <span
                            className={cn('readout text-xs', over ? 'text-status-blocked' : 'text-muted-foreground')}
                            data-testid="instructions-bytes"
                        >
                            {bytes.toLocaleString()} of {maxBytes.toLocaleString()} bytes
                            {over && ': a run would refuse it'}
                        </span>
                        <span className="flex items-center gap-2">
                            <Button variant="ghost" size="sm" onClick={readAgain} disabled={reading}>
                                <RotateCw />
                                {reading ? 'Reading' : 'Read again'}
                            </Button>
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => onDraft(undefined)}
                                disabled={draft === undefined || mutation.isPending}
                            >
                                <Undo2 />
                                Revert
                            </Button>
                            <Button
                                size="sm"
                                onClick={() => mutation.mutate()}
                                disabled={draft === undefined || over || mutation.isPending}
                            >
                                <Save />
                                Save
                            </Button>
                        </span>
                    </div>
                    <Notice error={mutation.error}>
                        {mutation.isSuccess && draft === undefined ? `Saved ${file.path}.` : null}
                    </Notice>
                </>
            )}
        </div>
    )
}
