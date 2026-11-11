import { Copy, Download } from 'lucide-react'

import { CopyablePath } from '@/components/copy-button'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { saveFile } from '@/lib/save-file'

/**
 * `Copy Markdown` and `Save .md`: a plan's Markdown whole, or a task's report's, onto the clipboard or into a file, for
 * a PR, another agent, or a review. What leaves is what the page shows, read as the button is pressed, edits not yet
 * saved included, which the toast then says. A file is named as `canopy archive` names a plan (`file_name`), so one
 * plan has one name whichever way it left. The clipboard needs a secure context (https, or localhost), so elsewhere
 * `Copy Markdown` is not drawn, and `Save .md`, which needs none, stays.
 */
export function PlanMarkdownActions({
    markdown,
    fileName,
    what = 'plan',
    unsaved = false,
}: {
    /** The Markdown as the page shows it, read when a button is pressed. */
    markdown: () => string
    /** What a save names the file, as the server names it. */
    fileName: string
    /** What the Markdown is, in a word, for the toasts: `plan`, `report`. */
    what?: string
    /** Whether the page holds edits not yet saved to the file, which go with a copy or a save. */
    unsaved?: boolean
}) {
    const toast = useToast()
    const edits = unsaved ? ', with your unsaved edits' : ''

    function copy() {
        navigator.clipboard
            .writeText(markdown())
            .then(() => toast({ title: `Copied the ${what}'s Markdown${edits}`, tone: 'done' }))
            .catch(() =>
                toast({
                    title: `Could not copy the ${what}'s Markdown`,
                    detail: 'The browser refused the clipboard.',
                    tone: 'failed',
                }),
            )
    }

    function save() {
        saveFile(new Blob([markdown()], { type: 'text/markdown' }), fileName)
        toast({ title: `Saved the ${what}'s Markdown${edits}`, detail: fileName, tone: 'done' })
    }

    // Icons, named on hover and to a screen reader, as the change steps beside them are: a plan's header already holds
    // its modes in words, and two more would wrap it onto a second line on all but the widest page.
    return (
        <span className="flex items-center">
            {globalThis.isSecureContext && (
                <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Copy Markdown"
                    title={`Copy the ${what}'s Markdown`}
                    onClick={copy}
                >
                    <Copy aria-hidden />
                </Button>
            )}
            <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label="Save .md"
                title={`Save as ${fileName}`}
                onClick={save}
            >
                <Download aria-hidden />
            </Button>
        </span>
    )
}

/**
 * Where a plan's file is, as a readout under its page's description, copied whole by the button beside it: a plan is a
 * file so the operator can use their own tools on it (docs/design/PLANNING.md §25).
 */
export function PlanFileLine({ path }: { path: string }) {
    return (
        <p className="mt-1 flex min-w-0 items-center gap-2 text-xs text-muted-foreground" data-testid="plan-file">
            <span className="panel-label">file</span>
            <span className="min-w-0 font-mono" data-testid="plan-path">
                <CopyablePath path={path} label="plan path" />
            </span>
        </p>
    )
}
