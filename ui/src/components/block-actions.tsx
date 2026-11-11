import { Copy, Download, ImageDown } from 'lucide-react'
import { useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { CopyButton } from '@/components/copy-button'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useToast } from '@/hooks/use-toast'
import { blockSlots } from '@/lib/block-slots'
import type { BlockSlot } from '@/lib/block-slots'
import { diagramPng, diagramSurface, kindWord } from '@/lib/diagram-picture'
import { savedSvg } from '@/lib/diagram-svg'
import { saveFile } from '@/lib/save-file'

/** A diagram's picture as the page shows it, and the kind mermaid read it as. */
export interface DrawnPicture {
    /** The SVG of the image shown. */
    svg: string
    /** The kind mermaid read it as: `flowchart-v2`, `sequence`, and so on. */
    kind: string
}

/**
 * A block's actions, at its top right corner over it (`block-actions`, src/index.css): what takes the block elsewhere,
 * a diagram's source or picture, a code block's text. They show while the block, an ancestor marked `group/block`, is
 * hovered, or one of them holds the focus or its menu is open, and always on a touch screen. The block is positioned,
 * so they sit in its corner.
 */
export function BlockActions({ children }: { children: ReactNode }) {
    return <div className="block-actions">{children}</div>
}

/**
 * A diagram's actions: its Mermaid source copied, exactly as the fence holds it, without the fence's lines; and once it
 * is drawn, its picture copied as an image or saved as a PNG or an SVG, named `name` (`ABC-102-plan-2-sequence-1`).
 */
export function DiagramActions({
    source,
    drawn,
    name,
}: {
    /** The diagram's Mermaid source. */
    source: string
    /** Its picture, once drawn: none while it is drawn, or when it could not be. */
    drawn?: DrawnPicture | undefined
    /** What a file of its picture is named, without its extension. */
    name: string
}) {
    return (
        <>
            <CopyButton text={source} label="Mermaid source" />
            {drawn !== undefined && <PictureMenu svg={drawn.svg} name={name} />}
        </>
    )
}

/** A code block's actions: its code copied, exactly as the fence holds it, without the fence's lines. */
export function CodeActions({ text }: { text: string }) {
    return <CopyButton text={text} label="code" />
}

/**
 * The actions of the blocks of a plan's document, the editor `owner`'s, each drawn into its block's room for them
 * (`src/lib/block-slots.ts`): through a portal, so they render in the page's tree, with its toasts, though ProseMirror
 * draws the block around them. A diagram's picture is saved named `name`, then its kind and which of its document's
 * diagrams it is, in the document's order: `ABC-102-plan-2-sequence-1`.
 */
export function PlanBlockActions({ owner, name }: { owner: object; name: string }) {
    const slots = blockSlots(owner)
    const blocks = inDocumentOrder(useSyncExternalStore(slots.subscribe, slots.snapshot))
    // Each diagram's place among the document's diagrams, by its id.
    const diagrams = blocks.filter((block) => block.kind === 'diagram').map((block) => block.id)
    return blocks.map((block) => {
        if (block.kind === 'code') {
            return createPortal(<CodeActions text={block.text} />, block.slot, String(block.id))
        }
        const place = diagrams.indexOf(block.id) + 1
        return createPortal(
            <DiagramActions
                source={block.source}
                drawn={block.drawn}
                name={`${name}-${kindWord(block.drawn?.kind ?? '')}-${place}`}
            />,
            block.slot,
            String(block.id),
        )
    })
}

// `blocks` in the order their rooms sit in the page, which is the document's: they are registered as their views are
// made, which an edit can do in any order.
function inDocumentOrder(blocks: readonly BlockSlot[]): BlockSlot[] {
    return blocks.toSorted((a, b) =>
        (a.slot.compareDocumentPosition(b.slot) & Node.DOCUMENT_POSITION_PRECEDING) === 0 ? -1 : 1,
    )
}

// A drawn diagram's picture, copied as an image or saved as a PNG or an SVG, from a menu of its own: the source's copy
// is the one action most wanted, and these are its other forms. The SVG is the picture cut down to canopy's lists
// (`src/lib/diagram-svg.ts`), never mermaid's as it came, since a file opened on its own is a document (D131).
// Copying needs the clipboard, which a page reaches only in a secure context, and an image on it, which a browser
// without `ClipboardItem` cannot put there.
function PictureMenu({ svg, name }: { svg: string; name: string }) {
    const toast = useToast()
    const file = `${name}.png`
    const canCopy = globalThis.isSecureContext && 'ClipboardItem' in globalThis
    async function save() {
        try {
            saveFile(await diagramPng(svg, diagramSurface()), file)
            toast({ title: 'Saved the diagram as a PNG', detail: file, tone: 'done' })
        } catch (error) {
            toast({ title: 'Could not save the diagram', detail: reason(error), tone: 'failed' })
        }
    }
    function saveVector() {
        const vector = `${name}.svg`
        try {
            const { svg: saved } = savedSvg(svg, diagramSurface())
            saveFile(new Blob([saved], { type: 'image/svg+xml' }), vector)
            toast({ title: 'Saved the diagram as an SVG', detail: vector, tone: 'done' })
        } catch (error) {
            toast({ title: 'Could not save the diagram', detail: reason(error), tone: 'failed' })
        }
    }
    async function copy() {
        try {
            // The PNG is a promise the clipboard waits on, so the copy keeps the click that asked for it, as Safari
            // needs.
            await navigator.clipboard.write([new ClipboardItem({ 'image/png': diagramPng(svg, diagramSurface()) })])
            toast({ title: 'Copied the diagram as an image', detail: file, tone: 'done' })
        } catch (error) {
            toast({ title: 'Could not copy the diagram', detail: reason(error), tone: 'failed' })
        }
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Copy or save the picture"
                    title="Copy or save the picture"
                    className="-my-1"
                >
                    <ImageDown />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {canCopy && (
                    <DropdownMenuItem onSelect={() => void copy()}>
                        <Copy aria-hidden />
                        Copy as image
                    </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={() => void save()}>
                    <Download aria-hidden />
                    Save as PNG
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={saveVector}>
                    <Download aria-hidden />
                    Save as SVG
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

// What went wrong, in a line for a toast.
function reason(error: unknown): string {
    if (error instanceof DOMException && error.name === 'NotAllowedError') {
        return 'The browser refused the clipboard.'
    }
    return error instanceof Error ? error.message : String(error)
}
