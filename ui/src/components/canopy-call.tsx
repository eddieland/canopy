import type { TranscriptTool } from '@/api/types'
import { MarkedText } from '@/components/marked-text'
import { RichText } from '@/components/rich-text'
import { Chip } from '@/components/status'
import { commitsOf, matchesOf, reviewItemsOf } from '@/lib/canopy-calls'
import type { CanopyCall, DiffLineKind, GrepFile, LoggedCommit, ReadItem } from '@/lib/canopy-calls'
import { cn } from '@/lib/utils'

/**
 * A call of one of canopy's own tools on its line (`canopyCall`): what it is about in the line's own color, the rest
 * of what it names muted, as a command's flags would be, then the first of what the agent said with it, in prose.
 * Its action is a chip beside it, the caller's. Search marks hold in each part.
 */
export function CanopyLine({ call, words }: { call: CanopyCall; words: readonly string[] }) {
    return (
        <>
            {call.subject !== null && (
                <span className="font-mono">
                    <MarkedText text={call.subject} words={words} />
                </span>
            )}
            {call.detail !== null && (
                <span className="font-mono text-muted-foreground">
                    {call.subject !== null && ' '}
                    <MarkedText text={call.detail} words={words} />
                </span>
            )}
            {call.said !== null && (
                <span>
                    {(call.subject !== null || call.detail !== null) && (
                        <span className="text-muted-foreground"> · </span>
                    )}
                    <MarkedText text={call.said.text.split('\n')[0] ?? ''} words={words} />
                </span>
            )}
        </>
    )
}

/**
 * What a call of one of canopy's own tools opens to before its input and output: what the agent said with it, laid
 * out as it wrote it, and what canopy answered where that reads better laid out than as JSON: the commits `git log`
 * listed, the lines `git grep` found, the review items `review-items` read. Built once the call is opened. All of it
 * is an agent's or a repository's text, rendered as text.
 */
export function CanopyBody({ entry, call }: { entry: TranscriptTool; call: CanopyCall }) {
    const commits = commitsOf(entry)
    const matches = matchesOf(entry)
    const items = reviewItemsOf(entry)
    return (
        <>
            {call.said !== null && (
                <Laid label={call.said.label}>
                    <RichText text={call.said.text} pullRequests className="max-w-[96ch]" />
                </Laid>
            )}
            {commits !== null && commits.length > 0 && <Commits commits={commits} />}
            {matches !== null && matches.length > 0 && <Matches files={matches} />}
            {items !== null && items.length > 0 && <Items items={items} />}
        </>
    )
}

/** One laid-out part of a call's body, under its label, in the well a call's input sits in. */
function Laid({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <div className="flex flex-col gap-1" data-testid="transcript-canopy">
            <span className="panel-label">{label}</span>
            <div className="max-h-96 overflow-auto rounded-sm border bg-background p-3">{children}</div>
        </div>
    )
}

/** The commits a `git log` listed: each its short id, its message's first line, its author, and when. */
function Commits({ commits }: { commits: readonly LoggedCommit[] }) {
    return (
        <Laid label={commits.length === 1 ? 'commit' : `${commits.length} commits`}>
            <ol className="flex flex-col gap-1 text-xs">
                {commits.map((c) => (
                    <li key={c.commit} className="flex items-baseline gap-3">
                        <span className="shrink-0 font-mono text-muted-foreground" title={c.commit}>
                            {c.commit.slice(0, 10)}
                        </span>
                        <span className="min-w-0 flex-1 wrap-break-word">{c.subject}</span>
                        <span className="hidden shrink-0 text-muted-foreground @lg:inline">{c.author}</span>
                        <span className="hidden shrink-0 readout text-muted-foreground @lg:inline" title={c.date}>
                            {c.date.slice(0, 10)}
                        </span>
                        <span className="w-14 shrink-0 text-right readout text-muted-foreground">
                            {c.files} {c.files === 1 ? 'file' : 'files'}
                        </span>
                    </li>
                ))}
            </ol>
        </Laid>
    )
}

/** The files a `git grep` found: each its path and how many lines match, then its lines by number, a match's line
 * in the line's own color and its context muted. */
function Matches({ files }: { files: readonly GrepFile[] }) {
    return (
        <Laid label={files.length === 1 ? 'found in 1 file' : `found in ${files.length} files`}>
            <ul className="flex flex-col gap-2 font-mono text-xs">
                {files.map((file) => (
                    <li key={file.path} className="flex flex-col gap-0.5">
                        <span className="flex items-baseline gap-2">
                            <span className="font-medium wrap-break-word">{file.path}</span>
                            <span className="shrink-0 readout text-muted-foreground">{file.matched}</span>
                        </span>
                        {file.lines.map((line) => (
                            <span key={line.line} className={cn('flex gap-3', !line.match && 'text-muted-foreground')}>
                                <span className="w-10 shrink-0 text-right readout text-muted-foreground select-none">
                                    {line.line}
                                </span>
                                <span className="min-w-0 wrap-break-word whitespace-pre-wrap">{line.text}</span>
                            </span>
                        ))}
                    </li>
                ))}
            </ul>
        </Laid>
    )
}

/** The review items a `review-items` read: each its number, what it is, who wrote it, and its text as read. */
function Items({ items }: { items: readonly ReadItem[] }) {
    return (
        <Laid label={items.length === 1 ? 'item read' : `${items.length} items read`}>
            <ol className="flex flex-col gap-3">
                {/* A call's items never reorder, and a number may repeat in what a connector read. */}
                {items.map((item, i) => (
                    <li key={i} className="flex flex-col gap-1">
                        <span className="flex flex-wrap items-center gap-2 text-xs">
                            <span className="readout text-muted-foreground">{item.number}</span>
                            <span className="font-mono">{item.item}</span>
                            {item.author !== '' && <span>{item.author}</span>}
                            {item.state !== null && <Chip word={item.state} />}
                            {item.worker && <Chip>worker</Chip>}
                            {!item.trusted && !item.worker && <Chip tone="blocked">untrusted</Chip>}
                        </span>
                        <p className="max-w-[96ch] text-sm wrap-break-word whitespace-pre-wrap">{item.body}</p>
                    </li>
                ))}
            </ol>
        </Laid>
    )
}

// Full class names, written out, so Tailwind finds them: each kind of diff line's tint and ink.
const DIFF_LINE: Record<DiffLineKind, string> = {
    file: 'font-medium',
    hunk: 'text-muted-foreground',
    add: 'bg-diff-add/12',
    del: 'bg-diff-del/12',
    ctx: '',
}

/**
 * The diff a `git diff` returned, in place of its output's plain block: every line as written, an added one on
 * `diff-add`'s tint and a removed one on `diff-del`'s, as a review's diff tints them, a hunk's header muted and a
 * file's in medium weight. Search marks hold in each line.
 */
export function DiffBlock({
    lines,
    words,
}: {
    lines: readonly { kind: DiffLineKind; text: string }[]
    words: readonly string[]
}) {
    return (
        <div className="flex flex-col gap-1" data-testid="transcript-diff">
            <span className="panel-label">output</span>
            <pre
                className={cn(
                    'max-h-96 overflow-auto rounded-sm border bg-background py-2',
                    'font-mono text-xs wrap-break-word whitespace-pre-wrap',
                )}
            >
                {/* A diff's lines never reorder. */}
                {lines.map((line, i) => (
                    <span key={i} className={cn('block min-h-4 px-2', DIFF_LINE[line.kind])}>
                        <MarkedText text={line.text} words={words} />
                    </span>
                ))}
            </pre>
        </div>
    )
}
