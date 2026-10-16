import { EditorContent, useEditor, useEditorState } from '@tiptap/react'
import type { Editor } from '@tiptap/react'
import { PluginKey } from '@tiptap/pm/state'
import { BubbleMenu } from '@tiptap/react/menus'
import {
    Bold,
    Code,
    Heading1,
    Heading2,
    Heading3,
    Italic,
    List,
    ListOrdered,
    ListTodo,
    MessageSquarePlus,
    Pilcrow,
    Redo2,
    SquareCode,
    Strikethrough,
    TextQuote,
    Undo2,
} from 'lucide-react'
import { useEffect, useEffectEvent, useState } from 'react'
import type { ReactNode } from 'react'

import { Panel, PanelHeader } from '@/components/panel'
import { AskForChanges, PlanThreads } from '@/components/plan-threads'
import type { Draft } from '@/components/plan-threads'
import { Button } from '@/components/ui/button'
import {
    Toolbar,
    ToolbarButton,
    ToolbarSeparator,
    ToolbarToggleGroup,
    ToolbarToggleItem,
} from '@/components/ui/toolbar'
import { anchorFor, anchorsOf, highlightsKey, PlanHighlights, withHighlight } from '@/lib/plan-highlights'
import type { Range } from '@/lib/plan-highlights'
import { planExtensions } from '@/lib/plan-schema'
import { addReply, addThread, inPlanOrder, removeThread, setResolved, withAnchors } from '@/lib/plan-threads'
import type { PlanThread } from '@/lib/plan-threads'
import { isApple } from '@/lib/send-key'
import { ariaKeys, keysLabel } from '@/lib/shortcut'

const APPLE = isApple(navigator.userAgent)
// The selection's bubble, by its key, so opening a comment can hide it.
const BUBBLE = new PluginKey('planBubble')
// How far below the top of the page the editor keeps what it scrolls into view, in pixels: the sticky toolbar's height
// (`min-h-9`) and a little air. A passage's highlight keeps the same as its scroll margin (`.plan-comment`).
const TOOLBAR_CLEARANCE = 48
// The shortcut that comments on the selection (`PlanHighlights`).
const COMMENT_KEYS = 'Mod-Alt-m'

/**
 * A plan in a rich editor, with the operator's comments on its passages beside it (docs/design/PLANNING.md §25,
 * Commenting on a plan). The plan is Markdown in and out (`src/lib/plan-schema.ts`): the operator edits it as a
 * document, through the toolbar or Markdown's own shortcuts (`## `, `- `, `**`), and `onChange` gets the Markdown
 * after each edit. Selecting text and pressing Comment, or ⌘⌥M (Ctrl+Alt+M), comments on that passage, the cursor
 * in the comment; while one is half written, it keeps its passage and takes the cursor back instead. The comments
 * stay on their passages as the plan is edited, by their words (`src/lib/plan-anchors.ts`), and a passage deleted
 * whole leaves its comment marked as gone. The threads are the caller's state, given as `threads` and changed through
 * `onThreadsChange`. `markdown` is read once: a new plan is a new `key`. With `onAskForChanges`, the comments end in
 * Ask for changes, which sends the open ones to the planner as one message (`changeRequest`).
 */
export function PlanEditor({
    markdown,
    threads,
    onThreadsChange,
    onChange,
    editable = true,
    onAskForChanges,
}: {
    /** The plan, as Markdown. Read when the editor opens. */
    markdown: string
    /** The comments on it. */
    threads: PlanThread[]
    /** Called with the threads after the operator comments, replies, resolves, or deletes, or an edit moves one. */
    onThreadsChange: (threads: PlanThread[]) => void
    /** Called with the plan's Markdown after each edit. */
    onChange?: (markdown: string) => void
    /** Whether the operator may edit the plan and its comments; without it both are read only. */
    editable?: boolean
    /** Sends the open comments, and a note on the whole plan, to the planner as one message. */
    onAskForChanges?: (message: string) => void
}) {
    const editor = useEditor({
        extensions: planExtensions([PlanHighlights]),
        content: markdown,
        contentType: 'markdown',
        editable,
        // The editor renders on the first pass, so the plan never paints empty first.
        immediatelyRender: true,
        // What a render shows is selected below (`useEditorState`), so a keystroke re-renders only what it changes.
        shouldRerenderOnTransaction: false,
        editorProps: {
            // What the editor scrolls into view (the cursor as it types, a passage shown from its comment) stays clear
            // of the toolbar, which sticks over the top of the page.
            scrollMargin: { top: TOOLBAR_CLEARANCE, bottom: 16, left: 0, right: 0 },
            scrollThreshold: { top: TOOLBAR_CLEARANCE, bottom: 16, left: 0, right: 0 },
            attributes: {
                class: 'plan-doc',
                'aria-label': 'Plan',
                'aria-multiline': 'true',
                role: 'textbox',
            },
        },
    })
    const [draft, setDraft] = useState<Draft | undefined>(undefined)
    const seen = useEditorState({
        editor,
        selector: ({ editor: current }) => {
            const highlights = highlightsKey.getState(current.state)
            return {
                // Where each found thread starts, in plan order: what the list's order and its `passage gone` follow.
                starts: [...(highlights?.ranges ?? new Map<string, Range>())].map(([id, range]) => [id, range.from]),
                active: highlights?.active,
                selected: !current.state.selection.empty,
            }
        },
    })
    const starts = new Map(seen.starts as [string, number][])
    const ordered = inPlanOrder(threads, starts)

    // The threads go to the highlights whenever they change; the plugin keeps the ranges it has and looks for the rest.
    useEffect(() => {
        const placed = threads.map(({ id, anchor, resolved }) => ({ id, anchor, resolved }))
        const tr = withHighlight(editor.state.tr, { kind: 'sync', threads: placed }).setMeta('addToHistory', false)
        editor.view.dispatch(tr)
    }, [editor, threads])

    useEffect(() => {
        editor.setEditable(editable)
    }, [editor, editable])

    // After an edit, the threads' passages may have moved or changed their words: save their anchors as they are now.
    const onEdit = useEffectEvent(() => {
        const next = withAnchors(threads, anchorsOf(editor.state).anchors)
        if (next !== threads) {
            onThreadsChange(next)
        }
        onChange?.(editor.getMarkdown())
    })
    const onPassageClick = useEffectEvent(({ id }: { id: string }) => activate(id, false))
    const onCommentKey = useEffectEvent(() => startComment())
    useEffect(() => {
        const edit = () => onEdit()
        const click = (event: { id: string }) => onPassageClick(event)
        const key = () => onCommentKey()
        editor.on('update', edit)
        editor.on('planThreadActivate', click)
        editor.on('planCommentRequest', key)
        return () => {
            editor.off('update', edit)
            editor.off('planThreadActivate', click)
            editor.off('planCommentRequest', key)
        }
    }, [editor])

    function startComment() {
        const { from, to, empty } = editor.state.selection
        const anchor = empty ? undefined : anchorFor(editor.state, from, to)
        if (!editable || anchor === undefined) {
            return
        }
        const opened = (draft?.opened ?? 0) + 1
        if (draft !== undefined && draft.body.trim() !== '') {
            // A comment half written stays on its passage, its words with it: the operator goes back to it rather than
            // lose it or carry it to other words.
            setDraft({ ...draft, opened })
            editor.view.dispatch(editor.state.tr.setMeta(BUBBLE, 'hide'))
            return
        }
        setDraft({ quote: anchor.quote, body: '', opened })
        // The bubble goes with the click that used it: the selection it sat over is now the draft's.
        const tr = withHighlight(editor.state.tr, { kind: 'draft', range: { from, to } }).setMeta(BUBBLE, 'hide')
        editor.view.dispatch(tr)
    }

    function cancelComment() {
        setDraft(undefined)
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'draft', range: undefined }))
    }

    function addComment(body: string) {
        const range = highlightsKey.getState(editor.state)?.draft
        const anchor = range && anchorFor(editor.state, range.from, range.to)
        setDraft(undefined)
        if (range === undefined || anchor === undefined) {
            // The passage was deleted while the comment was written; there is nothing left to put it on.
            cancelComment()
            return
        }
        const id = crypto.randomUUID()
        onThreadsChange(addThread(threads, { id, anchor, body, at: new Date().toISOString() }))
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'add', id, range }))
    }

    // Marks a thread the open one; from its card, the plan scrolls to its passage, and from its passage, the column to
    // its card.
    function activate(id: string, fromCard: boolean) {
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'activate', id }))
        const range = highlightsKey.getState(editor.state)?.ranges.get(id)
        if (fromCard && range !== undefined) {
            editor.commands.setTextSelection(range.from)
            // By its highlight: ProseMirror scrolls to its selection only while the page's selection is in the editor,
            // and the card's button holds it now. Its scroll margin keeps it clear of the toolbar (`src/index.css`).
            editor.view.dom.querySelector(`[data-thread="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' })
        } else if (!fromCard) {
            // The thread's card, not its highlight in the plan, which carries the same attribute.
            document.querySelector(`article[data-thread="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' })
        }
    }

    const open = threads.filter((thread) => !thread.resolved).length
    return (
        <div className="grid min-w-0 items-start gap-6 2xl:grid-cols-[minmax(0,1fr)_24rem]">
            <Panel>
                <PanelHeader label="Plan" sticky>
                    {editable && <FormatBar editor={editor} canComment={seen.selected} onComment={startComment} />}
                </PanelHeader>
                <EditorContent editor={editor} className="px-6 py-4" />
                {editable && (
                    <BubbleMenu
                        editor={editor}
                        pluginKey={BUBBLE}
                        options={{ placement: 'top' }}
                        className="rounded-md border bg-surface p-0.5"
                        data-testid="plan-bubble"
                    >
                        <Button
                            variant="ghost"
                            size="xs"
                            onClick={startComment}
                            title={withKeys('Comment', COMMENT_KEYS)}
                        >
                            <MessageSquarePlus aria-hidden />
                            Comment
                        </Button>
                    </BubbleMenu>
                )}
            </Panel>
            <Panel>
                <PanelHeader label="Comments">
                    <span className="readout text-xs text-muted-foreground">{open} open</span>
                </PanelHeader>
                <PlanThreads
                    threads={ordered}
                    found={new Set(starts.keys())}
                    active={seen.active}
                    draft={draft}
                    editable={editable}
                    onDraftChange={(body) => setDraft(draft && { ...draft, body })}
                    onDraftSubmit={addComment}
                    onDraftCancel={cancelComment}
                    onActivate={(id) => activate(id, true)}
                    onReply={(id, body) =>
                        onThreadsChange(
                            addReply(threads, id, { id: crypto.randomUUID(), body, at: new Date().toISOString() }),
                        )
                    }
                    onResolve={(id, resolved) => onThreadsChange(setResolved(threads, id, resolved))}
                    onDelete={(id) => onThreadsChange(removeThread(threads, id))}
                />
                {editable && onAskForChanges !== undefined && (
                    <AskForChanges threads={threads} starts={starts} onAsk={onAskForChanges} />
                )}
            </Panel>
        </div>
    )
}

// The block a paragraph is, as the text style group names it.
type BlockStyle = 'paragraph' | 'h1' | 'h2' | 'h3'
type MarkName = 'bold' | 'italic' | 'strike' | 'code'
type BlockName = 'bulletList' | 'orderedList' | 'taskList' | 'blockquote' | 'codeBlock'

// Each control with the shortcut the editor already binds to it (Tiptap's own, in its notation), which its tooltip
// names.
const MARKS: { name: MarkName; label: string; keys: string; icon: ReactNode }[] = [
    { name: 'bold', label: 'Bold', keys: 'Mod-b', icon: <Bold /> },
    { name: 'italic', label: 'Italic', keys: 'Mod-i', icon: <Italic /> },
    { name: 'strike', label: 'Strikethrough', keys: 'Mod-Shift-s', icon: <Strikethrough /> },
    { name: 'code', label: 'Code', keys: 'Mod-e', icon: <Code /> },
]

const BLOCKS: { name: BlockName; label: string; keys: string; icon: ReactNode }[] = [
    { name: 'bulletList', label: 'Bulleted list', keys: 'Mod-Shift-8', icon: <List /> },
    { name: 'orderedList', label: 'Numbered list', keys: 'Mod-Shift-7', icon: <ListOrdered /> },
    { name: 'taskList', label: 'Task list', keys: 'Mod-Shift-9', icon: <ListTodo /> },
    { name: 'blockquote', label: 'Quote', keys: 'Mod-Shift-b', icon: <TextQuote /> },
    { name: 'codeBlock', label: 'Code block', keys: 'Mod-Alt-c', icon: <SquareCode /> },
]

const STYLES: { name: BlockStyle; label: string; keys: string; icon: ReactNode }[] = [
    { name: 'paragraph', label: 'Text', keys: 'Mod-Alt-0', icon: <Pilcrow /> },
    { name: 'h1', label: 'Heading 1', keys: 'Mod-Alt-1', icon: <Heading1 /> },
    { name: 'h2', label: 'Heading 2', keys: 'Mod-Alt-2', icon: <Heading2 /> },
    { name: 'h3', label: 'Heading 3', keys: 'Mod-Alt-3', icon: <Heading3 /> },
]

const UNDO_KEYS = 'Mod-z'
const REDO_KEYS = 'Mod-Shift-z'

// The editor's toolbar: undo and redo, the paragraph's style, the marks, the blocks, and Comment. Each control is
// named for a screen reader and on hover, and shows what is in force at the cursor.
function FormatBar({ editor, canComment, onComment }: { editor: Editor; canComment: boolean; onComment: () => void }) {
    const state = useEditorState({
        editor,
        selector: ({ editor: current }) => ({
            marks: MARKS.filter((mark) => current.isActive(mark.name)).map((mark) => mark.name),
            blocks: BLOCKS.filter((block) => current.isActive(block.name)).map((block) => block.name),
            style: styleAt(current),
            undo: current.can().undo(),
            redo: current.can().redo(),
        }),
    })

    function toggleMark(name: MarkName) {
        const chain = editor.chain().focus()
        switch (name) {
            case 'bold': {
                chain.toggleBold().run()
                break
            }
            case 'italic': {
                chain.toggleItalic().run()
                break
            }
            case 'strike': {
                chain.toggleStrike().run()
                break
            }
            case 'code': {
                chain.toggleCode().run()
                break
            }
            default: {
                name satisfies never
            }
        }
    }

    function toggleBlock(name: BlockName) {
        const chain = editor.chain().focus()
        switch (name) {
            case 'bulletList': {
                chain.toggleBulletList().run()
                break
            }
            case 'orderedList': {
                chain.toggleOrderedList().run()
                break
            }
            case 'taskList': {
                chain.toggleTaskList().run()
                break
            }
            case 'blockquote': {
                chain.toggleBlockquote().run()
                break
            }
            case 'codeBlock': {
                chain.toggleCodeBlock().run()
                break
            }
            default: {
                name satisfies never
            }
        }
    }

    function setStyle(name: BlockStyle) {
        const chain = editor.chain().focus()
        switch (name) {
            case 'paragraph': {
                chain.setParagraph().run()
                break
            }
            case 'h1':
            case 'h2':
            case 'h3': {
                chain.setHeading({ level: Number(name.slice(1)) as 1 | 2 | 3 }).run()
                break
            }
            default: {
                name satisfies never
            }
        }
    }

    return (
        <Toolbar aria-label="Format" className="-mr-2 ml-auto">
            <ToolbarButton
                aria-label="Undo"
                title={withKeys('Undo', UNDO_KEYS)}
                aria-keyshortcuts={ariaKeys(UNDO_KEYS, APPLE)}
                disabled={!state.undo}
                onClick={() => {
                    editor.chain().focus().undo().run()
                }}
            >
                <Undo2 />
            </ToolbarButton>
            <ToolbarButton
                aria-label="Redo"
                title={withKeys('Redo', REDO_KEYS)}
                aria-keyshortcuts={ariaKeys(REDO_KEYS, APPLE)}
                disabled={!state.redo}
                onClick={() => {
                    editor.chain().focus().redo().run()
                }}
            >
                <Redo2 />
            </ToolbarButton>
            <ToolbarSeparator />
            <ToolbarToggleGroup
                type="single"
                aria-label="Text style"
                value={state.style ?? ''}
                // Pressing the style in force would leave none: a paragraph is always one of them, so it is kept.
                onValueChange={(value: string) => {
                    const style = STYLES.find((item) => item.name === value)
                    if (style !== undefined) {
                        setStyle(style.name)
                    }
                }}
            >
                {STYLES.map((style) => (
                    <ToolbarToggleItem
                        key={style.name}
                        value={style.name}
                        aria-label={style.label}
                        title={withKeys(style.label, style.keys)}
                        aria-keyshortcuts={ariaKeys(style.keys, APPLE)}
                    >
                        {style.icon}
                    </ToolbarToggleItem>
                ))}
            </ToolbarToggleGroup>
            <ToolbarSeparator />
            <ToolbarToggleGroup
                type="multiple"
                aria-label="Marks"
                value={state.marks}
                onValueChange={(value: string[]) => {
                    const flipped = MARKS.find((mark) => value.includes(mark.name) !== state.marks.includes(mark.name))
                    if (flipped !== undefined) {
                        toggleMark(flipped.name)
                    }
                }}
            >
                {MARKS.map((mark) => (
                    <ToolbarToggleItem
                        key={mark.name}
                        value={mark.name}
                        aria-label={mark.label}
                        title={withKeys(mark.label, mark.keys)}
                        aria-keyshortcuts={ariaKeys(mark.keys, APPLE)}
                    >
                        {mark.icon}
                    </ToolbarToggleItem>
                ))}
            </ToolbarToggleGroup>
            <ToolbarSeparator />
            <ToolbarToggleGroup
                type="multiple"
                aria-label="Blocks"
                value={state.blocks}
                onValueChange={(value: string[]) => {
                    const flipped = BLOCKS.find(
                        (block) => value.includes(block.name) !== state.blocks.includes(block.name),
                    )
                    if (flipped !== undefined) {
                        toggleBlock(flipped.name)
                    }
                }}
            >
                {BLOCKS.map((block) => (
                    <ToolbarToggleItem
                        key={block.name}
                        value={block.name}
                        aria-label={block.label}
                        title={withKeys(block.label, block.keys)}
                        aria-keyshortcuts={ariaKeys(block.keys, APPLE)}
                    >
                        {block.icon}
                    </ToolbarToggleItem>
                ))}
            </ToolbarToggleGroup>
            <ToolbarSeparator />
            <ToolbarButton
                size="xs"
                disabled={!canComment}
                onClick={onComment}
                title={withKeys('Comment on the selection', COMMENT_KEYS)}
                aria-keyshortcuts={ariaKeys(COMMENT_KEYS, APPLE)}
            >
                <MessageSquarePlus />
                Comment
            </ToolbarButton>
        </Toolbar>
    )
}

// The style of the paragraph at the cursor, or undefined in a block the group does not name (a code block).
function styleAt(editor: Editor): BlockStyle | undefined {
    for (const level of [1, 2, 3] as const) {
        if (editor.isActive('heading', { level })) {
            return `h${level}`
        }
    }
    return editor.isActive('paragraph') ? 'paragraph' : undefined
}

// A control's name with its shortcut, as its tooltip shows it: `Bold (Ctrl+B)`.
function withKeys(label: string, keys: string): string {
    return `${label} (${keysLabel(keys, APPLE)})`
}
