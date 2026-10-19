import { memorySegments } from '@/lib/memory'
import { cn } from '@/lib/utils'

/**
 * What a worker wrote, or the operator for a lesson, as plain text (DESIGN §28): never Markdown or a link, and every
 * character that hides text named by its code point (`<U+200B>`), set apart so it is seen, as the CLI shows it. With
 * `lines`, for a draft or a review comment, its line breaks and tabs show as written.
 */
export function MemoryText({ text, className, lines }: { text: string; className?: string; lines?: boolean }) {
    return (
        <span className={cn('break-words whitespace-pre-wrap', className)}>
            {memorySegments(text, { lines }).map((segment, i) =>
                segment.hidden ? (
                    <span
                        key={i}
                        title="A character that hides text, which a model still reads"
                        className="rounded-xs border border-status-failed/40 bg-status-failed/10 font-mono text-2xs"
                    >
                        {segment.text}
                    </span>
                ) : (
                    <span key={i}>{segment.text}</span>
                ),
            )}
        </span>
    )
}
