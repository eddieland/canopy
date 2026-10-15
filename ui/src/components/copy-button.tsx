import { Check, Copy, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { useWholePath } from '@/hooks/use-whole-path'
import { cn } from '@/lib/utils'

/** How long the button shows what its last click did before it reads Copy again. */
const SHOWN_MS = 1500

/**
 * Text the operator may want to paste elsewhere (a branch, a path, a session id), then a `CopyButton` for it. The text
 * wraps anywhere, as a field's value does; `children` shows something other than what is copied, such as a commit's
 * first 7 characters for its whole hash.
 */
export function Copyable({
    text,
    label,
    children,
    reveal = false,
    className,
}: {
    /** What the button copies, exactly as written. */
    text: string
    /** What the text is, in a few words: `branch`, `log path`. */
    label: string
    /** What shows in place of `text`, when that is not the text itself. */
    children?: ReactNode
    /** Show the button only while its row is hovered, as `CopyButton`'s `reveal` does. */
    reveal?: boolean
    /** Classes for the whole, such as its font. */
    className?: string
}) {
    return (
        <span className={cn('inline-flex max-w-full min-w-0 items-center gap-1', className)}>
            <span className="min-w-0 break-all">{children ?? text}</span>
            <CopyButton text={text} label={label} reveal={reveal} />
        </span>
    )
}

/**
 * A path the server shows from the workspace root, then a `CopyButton` that copies it whole, joined to the root the
 * server's meta gives. Until the root is known there is no button, so a copy never puts the short path on the
 * clipboard.
 */
export function CopyablePath({
    path,
    label,
    children,
}: {
    /** The path as the server sent it: from the workspace root when under it, else whole. */
    path: string
    /** What the path is, in a few words: `log path`. */
    label: string
    /** What shows in place of `path`, when that is not the path itself. */
    children?: ReactNode
}) {
    const whole = useWholePath()
    if (whole === undefined) {
        return <span className="min-w-0 break-all">{children ?? path}</span>
    }
    return (
        <Copyable text={whole(path)} label={label}>
            {children ?? path}
        </Copyable>
    )
}

/**
 * A ghost icon button that puts `text` on the clipboard: a branch, a path, a session id, a commit. It shows a check in
 * the accent once copied, or a cross in `status-failed` if the browser refused, then its copy icon again, and a toast
 * says so with the text it copied, which a screen reader announces. The page can reach the clipboard only in a secure
 * context (https, or localhost), so elsewhere it renders nothing, the same on every render, and the text beside it
 * stays selectable.
 */
export function CopyButton({
    text,
    label,
    reveal = false,
    className,
}: {
    /** What a click copies, exactly as written. */
    text: string
    /** What the text is, in a few words, naming the button for a screen reader and on hover: `branch`, `log path`. */
    label: string
    /**
     * Show it only while the pointer is over its row, an ancestor marked `group/copy`, or it has the focus, for a dense
     * list where a button on every line would be noise. It keeps its space either way, and shows always on a touch
     * screen, which has no hover.
     */
    reveal?: boolean
    /** Classes for the button. */
    className?: string
}) {
    const [shown, setShown] = useState<'copy' | 'copied' | 'failed'>('copy')
    const toast = useToast()
    useEffect(() => {
        if (shown === 'copy') {
            return
        }
        const timer = globalThis.setTimeout(() => setShown('copy'), SHOWN_MS)
        return () => globalThis.clearTimeout(timer)
    }, [shown])
    if (!globalThis.isSecureContext) {
        return null
    }
    // What the click did: on the button until it reads Copy again, and in a toast with what it copied.
    function report(outcome: 'copied' | 'failed') {
        setShown(outcome)
        toast(
            outcome === 'copied'
                ? { title: `Copied ${label}`, detail: text, tone: 'done' }
                : { title: `Could not copy ${label}`, detail: 'The browser refused the clipboard.', tone: 'failed' },
        )
    }
    const name = shown === 'copy' ? `Copy ${label}` : shown === 'copied' ? `Copied ${label}` : `Could not copy ${label}`
    return (
        <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label={name}
            title={name}
            data-testid="copy"
            data-shown={shown}
            className={cn(
                '-my-1 shrink-0',
                reveal && 'opacity-0 group-hover/copy:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100',
                // Once clicked it stays until it reads Copy again, so what the click did is seen.
                reveal && shown !== 'copy' && 'opacity-100',
                className,
            )}
            onClick={() => {
                navigator.clipboard
                    .writeText(text)
                    .then(() => report('copied'))
                    .catch(() => report('failed'))
            }}
        >
            {shown === 'copy' && <Copy />}
            {shown === 'copied' && <Check className="text-accent" />}
            {shown === 'failed' && <X className="text-status-failed" />}
        </Button>
    )
}
