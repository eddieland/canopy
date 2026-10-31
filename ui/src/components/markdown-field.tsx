import { Bold, Code, Heading2, List, ListOrdered, SquareCode } from 'lucide-react'
import { useId, useLayoutEffect, useRef, useState } from 'react'
import type { ComponentProps, KeyboardEvent, ReactNode } from 'react'

import { RichText } from '@/components/rich-text'
import {
    Toolbar,
    ToolbarButton,
    ToolbarSeparator,
    ToolbarToggleGroup,
    ToolbarToggleItem,
} from '@/components/ui/toolbar'
import { applyEdit, continueList, toggleCodeBlock, toggleLinePrefix, toggleMark } from '@/lib/markdown-edit'
import type { Edit, Selection } from '@/lib/markdown-edit'
import { isApple } from '@/lib/send-key'
import { ariaKeys, isPressed, keysLabel } from '@/lib/shortcut'
import { cn } from '@/lib/utils'

const APPLE = isApple(navigator.userAgent)

/** How tall the field starts and how tall it grows before it scrolls. */
export type MarkdownFieldSize = 'line' | 'default' | 'tall'

/**
 * Whether the field shows what it will look like: `off`; `tab`, a Write and a Preview the operator switches between;
 * or `live`, the preview beside the text as it is written, or under it in a narrow place.
 */
export type MarkdownPreview = 'off' | 'tab' | 'live'

// Each size's text, as tall as what it holds between its least and its most (`field-sizing-content`), then scrolling.
// `line` is one line, an `Input`'s `h-9` with the box's hairline; `default` a reply's few lines; `tall` a long note or
// brief.
// Written out so Tailwind finds them.
const SIZE: Record<MarkdownFieldSize, { text: string; most: string }> = {
    line: { text: 'min-h-8.5 py-1.75 leading-5', most: 'max-h-60' },
    default: { text: 'min-h-24 py-2 leading-relaxed', most: 'max-h-96' },
    tall: { text: 'min-h-60 py-2 leading-relaxed', most: 'max-h-144' },
}

// The shortcut that switches between Write and Preview, as GitHub's comment box takes it.
const PREVIEW_KEYS = 'Mod-Shift-p'

// What the toolbar writes: each a form `RichText` draws, so the field offers what the conversation shows and no more.
interface Tool {
    label: string
    icon: ReactNode
    keys?: string
    edit: (text: string, selection: Selection) => Edit
}

const MARKS: Tool[] = [
    { label: 'Bold', icon: <Bold />, keys: 'Mod-b', edit: (text, at) => toggleMark(text, at, 'strong') },
    { label: 'Code', icon: <Code />, keys: 'Mod-e', edit: (text, at) => toggleMark(text, at, 'code') },
]

const BLOCKS: Tool[] = [
    { label: 'Heading', icon: <Heading2 />, edit: (text, at) => toggleLinePrefix(text, at, 'heading') },
    { label: 'Bulleted list', icon: <List />, edit: (text, at) => toggleLinePrefix(text, at, 'bullet') },
    { label: 'Numbered list', icon: <ListOrdered />, edit: (text, at) => toggleLinePrefix(text, at, 'ordered') },
    { label: 'Code block', icon: <SquareCode />, edit: toggleCodeBlock },
]

/**
 * A text field for what the operator writes to an agent, in the Markdown agents read and the conversation draws
 * (`RichText`): a toolbar of what that holds under the text, **bold**, `code`, a heading, the two lists, and a code
 * block, and their shortcuts, ⌘B and ⌘E (Ctrl+B and Ctrl+E). Enter in a list item starts the next, and on an empty one
 * ends the list. An edit goes through the browser where it can, so ⌘Z undoes it as it does typing. With `preview`, it
 * shows the text as it will read: `tab` behind a Preview toggle (⌘⇧P), at the height of the text it replaces; `live`
 * beside it, or under it where the field is narrow.
 *
 * It is controlled: `value` and `onValueChange`. The rest of its props are the textarea's, `onKeyDown` first among the
 * keys it handles, so a send key (`useSendKeys`) sends before Enter continues a list. Name it with a `<label htmlFor>`
 * on `id`, or `aria-label`: not a `<label>` around it, which would name the toolbar's first button. The toolbar sits
 * under the text, as a chat's does, so Tab reaches the text first and the toolbar, one stop, after it.
 */
export function MarkdownField({
    value,
    onValueChange,
    size = 'default',
    preview = 'tab',
    toolbar = true,
    pullRequests = false,
    id,
    ref,
    onKeyDown,
    className,
    ...props
}: Omit<ComponentProps<'textarea'>, 'value' | 'onChange' | 'children' | 'className'> & {
    /** What the field holds, as Markdown. */
    value: string
    /** Called with what it holds after each change, typed or from the toolbar. */
    onValueChange: (value: string) => void
    /** How tall it starts and grows: `line`, `default`, or `tall`. */
    size?: MarkdownFieldSize
    /** Whether, and how, it shows the text as it will read: `off`, `tab`, or `live`. */
    preview?: MarkdownPreview
    /** Whether the formatting toolbar shows; its shortcuts work without it. */
    toolbar?: boolean
    /** Whether a GitHub PR's address in the preview is named as the PR, as the conversation names it. */
    pullRequests?: boolean
    /** Classes for the field's box, such as its width or a tint while focused. */
    className?: string
}) {
    const ownId = useId()
    const fieldId = id ?? ownId
    const area = useRef<HTMLTextAreaElement>(null)
    const write = useRef<HTMLButtonElement>(null)
    // The selection an edit leaves, set once React has written the text it made, where the browser could not make it.
    const pending = useRef<Selection | undefined>(undefined)
    const [previewing, setPreviewing] = useState(false)
    // The text's height when Preview took its place, so the preview starts as tall and nothing under it moves.
    const [height, setHeight] = useState<number | undefined>(undefined)
    const sized = SIZE[size]
    const showsText = preview !== 'tab' || !previewing
    const showsPreview = preview === 'live' || (preview === 'tab' && previewing)

    useLayoutEffect(() => {
        const selection = pending.current
        if (selection !== undefined && area.current !== null) {
            area.current.setSelectionRange(selection.start, selection.end)
            pending.current = undefined
        }
    })

    function apply(edit: Edit) {
        const field = area.current
        if (field === null) {
            return
        }
        field.focus()
        field.setSelectionRange(edit.from, edit.to)
        if (insertNatively(edit)) {
            field.setSelectionRange(edit.selection.start, edit.selection.end)
            return
        }
        pending.current = edit.selection
        onValueChange(applyEdit(field.value, edit))
    }

    function format(tool: Tool) {
        const field = area.current
        if (field !== null) {
            apply(tool.edit(field.value, { start: field.selectionStart, end: field.selectionEnd }))
        }
    }

    function showPreview(on: boolean) {
        if (on) {
            setHeight(area.current?.offsetHeight)
        }
        setPreviewing(on)
        // The keyboard stays where the operator was: on Write, which brings the text back, or back in the text.
        requestAnimationFrame(() => (on ? write.current : area.current)?.focus())
    }

    function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
        onKeyDown?.(event)
        if (event.defaultPrevented || event.nativeEvent.isComposing) {
            return
        }
        const tool = [...MARKS, ...BLOCKS].find((each) => each.keys !== undefined && isPressed(each.keys, event, APPLE))
        if (tool !== undefined) {
            event.preventDefault()
            format(tool)
            return
        }
        if (preview === 'tab' && isPressed(PREVIEW_KEYS, event, APPLE)) {
            event.preventDefault()
            showPreview(true)
            return
        }
        if (event.key === 'Enter' && !event.ctrlKey && !event.metaKey && !event.altKey) {
            const target = event.currentTarget
            const edit = continueList(target.value, { start: target.selectionStart, end: target.selectionEnd })
            if (edit !== undefined) {
                event.preventDefault()
                apply(edit)
            }
        }
    }

    return (
        <div
            className={cn(
                '@container flex flex-col rounded-md border bg-surface-raised text-sm text-foreground',
                'focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50',
                props.disabled === true && 'opacity-50',
                className,
            )}
        >
            <div className={cn('grid min-w-0', preview === 'live' && '@2xl:grid-cols-2')}>
                <textarea
                    ref={(node) => {
                        area.current = node
                        // The caller's ref sees the same textarea, as a plain field's would.
                        if (typeof ref === 'function') {
                            ref(node)
                        } else if (ref !== null && ref !== undefined) {
                            ref.current = node
                        }
                    }}
                    id={fieldId}
                    value={value}
                    hidden={!showsText}
                    onChange={(event) => onValueChange(event.target.value)}
                    onKeyDown={keyDown}
                    className={cn(
                        'block w-full field-sizing-content resize-none bg-transparent px-2.5 outline-none',
                        'placeholder:text-muted-foreground',
                        sized.text,
                        sized.most,
                    )}
                    {...props}
                />
                {showsPreview && (
                    <section
                        aria-label="Preview"
                        style={preview === 'tab' && height !== undefined ? { minHeight: height } : undefined}
                        className={cn(
                            'min-w-0 overflow-y-auto px-2.5 outline-none',
                            sized.text,
                            sized.most,
                            preview === 'live' && 'border-t @2xl:border-t-0 @2xl:border-l',
                        )}
                    >
                        {value.trim() === '' ? (
                            <p className="text-muted-foreground">nothing to preview yet</p>
                        ) : (
                            // The field is raised, so code in the preview sits on the canvas to stand apart from it.
                            <RichText text={value} pullRequests={pullRequests} raised />
                        )}
                    </section>
                )}
            </div>
            {(toolbar || preview === 'tab') && (
                <Toolbar aria-label="Formatting" aria-controls={fieldId} className="border-t px-1 py-0.5">
                    {toolbar && (
                        <>
                            <Tools tools={MARKS} disabled={!showsText || props.disabled === true} onTool={format} />
                            <ToolbarSeparator />
                            <Tools tools={BLOCKS} disabled={!showsText || props.disabled === true} onTool={format} />
                        </>
                    )}
                    {preview === 'tab' && (
                        <ToolbarToggleGroup
                            type="single"
                            aria-label="Mode"
                            value={previewing ? 'preview' : 'write'}
                            onValueChange={(mode: string) => {
                                // A click on the mode already on clears the group; it stays as it is.
                                if (mode !== '') {
                                    showPreview(mode === 'preview')
                                }
                            }}
                            className="ml-auto"
                        >
                            <ToolbarToggleItem
                                ref={write}
                                value="write"
                                size="xs"
                                title={withKeys('Write', PREVIEW_KEYS)}
                            >
                                Write
                            </ToolbarToggleItem>
                            <ToolbarToggleItem
                                value="preview"
                                size="xs"
                                title={withKeys('Preview', PREVIEW_KEYS)}
                                aria-keyshortcuts={ariaKeys(PREVIEW_KEYS, APPLE)}
                            >
                                Preview
                            </ToolbarToggleItem>
                        </ToolbarToggleGroup>
                    )}
                </Toolbar>
            )}
        </div>
    )
}

function Tools({ tools, disabled, onTool }: { tools: Tool[]; disabled: boolean; onTool: (tool: Tool) => void }) {
    return tools.map((tool) => (
        <ToolbarButton
            key={tool.label}
            aria-label={tool.label}
            title={tool.keys === undefined ? tool.label : withKeys(tool.label, tool.keys)}
            aria-keyshortcuts={tool.keys === undefined ? undefined : ariaKeys(tool.keys, APPLE)}
            disabled={disabled}
            // The text keeps the focus and its selection, so a click formats what was selected.
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onTool(tool)}
        >
            {tool.icon}
        </ToolbarButton>
    ))
}

// Makes the edit as typing would, over the selection the field holds, so the browser's undo takes it back. Where the
// browser has no such command (a test's DOM), it reports so and the caller sets the text itself.
function insertNatively(edit: Edit): boolean {
    if (edit.insert === '' && edit.from === edit.to) {
        return true
    }
    if (!('execCommand' in document)) {
        return false
    }
    // oxlint-disable-next-line typescript/no-deprecated -- the one edit a textarea's own undo history keeps
    return edit.insert === '' ? document.execCommand('delete') : document.execCommand('insertText', false, edit.insert)
}

function withKeys(label: string, keys: string): string {
    return `${label} (${keysLabel(keys, APPLE)})`
}
