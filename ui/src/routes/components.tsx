import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Send } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { metaQuery } from '@/api/queries'
import { Input, SearchField, Textarea } from '@/components/input'
import { MarkdownField } from '@/components/markdown-field'
import type { MarkdownFieldSize, MarkdownPreview } from '@/components/markdown-field'
import { None } from '@/components/none'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'

/**
 * The UI's shared pieces, each drawn live, on mock data alone: where a primitive (ui/DESIGN.md, "Primitives") is tried
 * in its sizes and states before a page uses it, and where a change to one is seen whole. Nothing here is saved.
 */
export const Route = createFileRoute('/components')({
    component: ComponentsPage,
})

function ComponentsPage() {
    const meta = useQuery(metaQuery).data
    return (
        <>
            <PageHeader root="Samples" title="Components">
                The pieces every page is built from, each live in its sizes and states. Nothing here is saved.
            </PageHeader>
            {meta === undefined && (
                <Panel>
                    <PanelSkeleton rows={4} className="min-h-72" />
                </Panel>
            )}
            {meta?.mock === false && (
                <Panel>
                    <Empty size="panel">no samples here: they show over the mock journal alone</Empty>
                </Panel>
            )}
            {meta?.mock === true && (
                <>
                    <MarkdownFields />
                    <TextFields />
                    <Buttons />
                    <Chips />
                    <Nothing />
                </>
            )}
        </>
    )
}

// What a sample field starts with: a little of each form the conversation draws.
const SAMPLE = [
    '## Next steps',
    '- Use the **v2** API, not `v1`',
    '- Run `make check` before pushing',
    '',
    '```',
    'uv run pytest -q tests/canopy/runs',
    '```',
].join('\n')

// Each way MarkdownField is used, by what it is for.
const FIELDS: { label: string; size: MarkdownFieldSize; preview: MarkdownPreview; toolbar: boolean; text: string }[] = [
    { label: 'default, tab preview: a reply', size: 'default', preview: 'tab', toolbar: true, text: SAMPLE },
    { label: 'tall, live preview: a long brief', size: 'tall', preview: 'live', toolbar: true, text: SAMPLE },
    { label: 'line, no toolbar or preview: a task', size: 'line', preview: 'off', toolbar: false, text: '' },
]

function MarkdownFields() {
    return (
        <Panel>
            <PanelHeader label="MarkdownField" />
            <div className="flex flex-col gap-5 p-3">
                {FIELDS.map((field) => (
                    <MarkdownSample key={field.label} {...field} />
                ))}
            </div>
        </Panel>
    )
}

function MarkdownSample({
    label,
    size,
    preview,
    toolbar,
    text,
}: {
    label: string
    size: MarkdownFieldSize
    preview: MarkdownPreview
    toolbar: boolean
    text: string
}) {
    const [value, setValue] = useState(text)
    return (
        <Sample label={label}>
            <MarkdownField
                aria-label={label}
                value={value}
                onValueChange={setValue}
                size={size}
                preview={preview}
                toolbar={toolbar}
                rows={size === 'line' ? 1 : undefined}
                placeholder="Write in the Markdown the conversation draws"
            />
        </Sample>
    )
}

function TextFields() {
    const [query, setQuery] = useState('')
    return (
        <Panel>
            <PanelHeader label="Text fields" />
            <div className="flex flex-col gap-5 p-3">
                <Sample label="Input">
                    <Input aria-label="Input" placeholder="One line, beside a form's buttons" />
                </Sample>
                <Sample label="Textarea: text shown as written">
                    <Textarea
                        aria-label="Textarea"
                        placeholder="A notice or a review request's notes, shown as plain text"
                    />
                </Sample>
                <Sample label="SearchField, default and sm">
                    <div className="flex flex-col gap-2">
                        <SearchField
                            aria-label="Search"
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            onClear={() => setQuery('')}
                            clearLabel="Clear the search"
                            placeholder="Filter a list"
                        />
                        <SearchField
                            size="sm"
                            aria-label="Search, small"
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            onClear={() => setQuery('')}
                            clearLabel="Clear the small search"
                            placeholder="Filter a panel's line"
                        />
                    </div>
                </Sample>
            </div>
        </Panel>
    )
}

// Every variant, in the sizes a page uses with words.
const VARIANTS = ['default', 'outline', 'secondary', 'ghost', 'destructive', 'link'] as const
const SIZES = ['default', 'sm', 'xs'] as const

function Buttons() {
    return (
        <Panel>
            <PanelHeader label="Button" />
            <div className="flex flex-col gap-3 p-3">
                {SIZES.map((size) => (
                    <Sample key={size} label={size}>
                        <div className="flex flex-wrap items-center gap-2">
                            {VARIANTS.map((variant) => (
                                <Button key={variant} type="button" variant={variant} size={size}>
                                    {variant === 'default' && <Send />}
                                    {variant}
                                </Button>
                            ))}
                        </div>
                    </Sample>
                ))}
            </div>
        </Panel>
    )
}

// Every tone a chip takes: a state's, then a feedback plan's proposals.
const TONES = ['plain', 'running', 'blocked', 'failed', 'change', 'decline', 'ask', 'leave'] as const

function Chips() {
    return (
        <Panel>
            <PanelHeader label="Chip" />
            <div className="flex flex-wrap items-center gap-2 p-3">
                {TONES.map((tone) => (
                    <Chip key={tone} tone={tone}>
                        {tone}
                    </Chip>
                ))}
            </div>
        </Panel>
    )
}

function Nothing() {
    return (
        <Panel>
            <PanelHeader label="Empty and None" />
            <Empty>no runs yet: the overseer starts one when it is due</Empty>
            <div className="flex flex-col gap-1 border-t p-3 text-sm">
                <None />
                <None reason="canopy only reviews it" />
            </div>
        </Panel>
    )
}

// One sample under its name.
function Sample({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="flex flex-col gap-1.5">
            <span className="panel-label">{label}</span>
            {children}
        </div>
    )
}
