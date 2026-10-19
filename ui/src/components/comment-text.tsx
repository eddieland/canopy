import { ChevronRight } from 'lucide-react'

import { MemoryText } from '@/components/memory-text'
import { Chip } from '@/components/status'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { foldDetails, hidesText } from '@/lib/details'
import type { CommentPart, Details } from '@/lib/details'
import { cn } from '@/lib/utils'

/**
 * A review comment as its author wrote it: plain text as `MemoryText` shows it, its line breaks kept and every hidden
 * character named, with each `<details>` block folded under its summary line, as GitHub shows it
 * (`src/lib/details.ts`). A block that folds a hidden character says so while closed, so a fold hides nothing the
 * operator would not see. Never Markdown or a link.
 */
export function CommentText({ text }: { text: string }) {
    return <Parts parts={foldDetails(text)} />
}

function Parts({ parts }: { parts: CommentPart[] }) {
    return parts.map((part, i) =>
        part.kind === 'text' ? <MemoryText key={i} text={part.text} lines /> : <Fold key={i} block={part} />,
    )
}

function Fold({ block }: { block: Details }) {
    return (
        <Collapsible defaultOpen={block.open} className="group/fold rounded-sm border" data-testid="comment-details">
            <CollapsibleTrigger
                className={cn(
                    'flex w-full cursor-pointer items-center gap-1.5 rounded-sm px-2 py-1 text-left outline-none',
                    'hover:bg-surface focus-visible:ring-3 focus-visible:ring-ring/50',
                )}
            >
                <ChevronRight
                    aria-hidden
                    className={cn(
                        'size-3 shrink-0 text-muted-foreground',
                        'group-data-[state=open]/fold:rotate-90 motion-safe:transition-transform',
                    )}
                />
                <MemoryText text={block.summary} className="min-w-0 flex-1 font-medium" />
                {hidesText(block.parts) && (
                    <Chip tone="failed" className="group-data-[state=open]/fold:hidden">
                        hides a character
                    </Chip>
                )}
            </CollapsibleTrigger>
            <CollapsibleContent className="flex flex-col gap-1.5 border-t px-2 py-1.5">
                <Parts parts={block.parts} />
            </CollapsibleContent>
        </Collapsible>
    )
}
