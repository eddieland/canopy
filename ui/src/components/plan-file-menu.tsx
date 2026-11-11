import { Copy, Download, FileDown } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/hooks/use-toast'
import { saveFile } from '@/lib/save-file'

/**
 * A plan's Markdown taken whole: copied, or saved as a file named `file`, the name `canopy archive` gives it, so one
 * plan has one name whichever way it left. What leaves is what the page shows, read when the item is picked
 * (`markdown`), the operator's edits included; while those are `unsaved`, its toast says so. Copying needs the
 * clipboard, which a page reaches only in a secure context; saving needs none.
 */
export function PlanFileMenu({
    markdown,
    file,
    unsaved = false,
    what = 'plan',
}: {
    /** The Markdown as the page shows it now. */
    markdown: () => string
    /** What a saved copy is named, with its extension. */
    file: string
    /** Whether the page holds edits its file does not have yet. */
    unsaved?: boolean
    /** What it is, in a word, for the toasts and the button's name: `plan`, `report`. */
    what?: string
}) {
    const toast = useToast()
    const note = unsaved ? 'with your edits, not saved yet' : undefined
    async function copy() {
        try {
            await navigator.clipboard.writeText(markdown())
            toast({ title: `Copied the ${what} as Markdown`, detail: note ?? file, tone: 'done' })
        } catch {
            toast({ title: `Could not copy the ${what}`, detail: 'The browser refused the clipboard.', tone: 'failed' })
        }
    }
    function save() {
        saveFile(new Blob([markdown()], { type: 'text/markdown;charset=utf-8' }), file)
        toast({ title: `Saved the ${what}`, detail: note === undefined ? file : `${file}, ${note}`, tone: 'done' })
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label={`Copy or save the ${what}`}
                    title={`Copy or save the ${what}`}
                >
                    <FileDown />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {globalThis.isSecureContext && (
                    <DropdownMenuItem onSelect={() => void copy()}>
                        <Copy aria-hidden />
                        Copy as Markdown
                    </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={save}>
                    <Download aria-hidden />
                    Save as .md
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
