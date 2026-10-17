import { EditorContent, useEditor, useEditorState } from '@tiptap/react'
import type { Editor } from '@tiptap/react'
import { PluginKey } from '@tiptap/pm/state'
import { Placeholder } from '@tiptap/extensions'
import { BubbleMenu } from '@tiptap/react/menus'
import {
    Bold,
    ChevronDown,
    Code,
    Italic,
    List,
    ListOrdered,
    ListTodo,
    MessageSquarePlus,
    Redo2,
    SquareCode,
    Strikethrough,
    Table,
    TextQuote,
    Undo2,
} from 'lucide-react'
import { Fragment, useEffect, useEffectEvent, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { Panel, PanelHeader } from '@/components/panel'
import { AskForChanges, DraftForm, PlanThreads, ThreadCard } from '@/components/plan-threads'
import type { Draft, ThreadActions } from '@/components/plan-threads'
import { Button } from '@/components/ui/button'
import { Toggle } from '@/components/ui/toggle'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
    Toolbar,
    ToolbarButton,
    ToolbarSeparator,
    ToolbarToggleGroup,
    ToolbarToggleItem,
} from '@/components/ui/toolbar'
import { anchorFor, anchorsOf, highlightsKey, PlanHighlights, withHighlight } from '@/lib/plan-highlights'
import type { Range } from '@/lib/plan-highlights'
import { changesKey, PlanChanges, textOf } from '@/lib/plan-diff'
import { alignComments, floatUnder } from '@/lib/plan-margin'
import { planExtensions } from '@/lib/plan-schema'
import {
    addReply,
    addThread,
    editReply,
    editThread,
    inPlanOrder,
    removeThread,
    setResolved,
    withAnchors,
} from '@/lib/plan-threads'
import type { PlanThread } from '@/lib/plan-threads'
import { isApple } from '@/lib/send-key'
import { cn } from '@/lib/utils'
import { ariaKeys, keysLabel } from '@/lib/shortcut'

const APPLE = isApple(navigator.userAgent)
// The selection's bubble, by its key, so opening a comment can hide it.
const BUBBLE = new PluginKey('planBubble')
// How far below the top of the page the editor keeps what it scrolls into view, in pixels: the sticky toolbar's height
// (`min-h-9`) and a little air. A passage's highlight keeps the same as its scroll margin (`.plan-comment`).
const TOOLBAR_CLEARANCE = 48
// How far above the bottom of the page: the bar of actions, which sticks there (`min-h-12`), and a little air.
const BAR_CLEARANCE = 64
// The shortcut that comments on the selection (`PlanHighlights`).
const COMMENT_KEYS = 'Mod-Alt-m'
// A comment floating under its passage, over the plan, while the comments sit under it.
const FLOAT = 'absolute z-20 w-[min(24rem,100%)] overflow-hidden rounded-md border bg-surface'

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
    edited = false,
    onAskForChanges,
    asked = false,
    actions,
    actionsNote,
    previous,
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
    /** Whether the plan was edited before it was opened here, as an edit made here marks it too. */
    edited?: boolean
    /** Sends the open comments, and a note on the whole plan, to the planner as one message. */
    onAskForChanges?: (message: string) => void
    /** Whether the operator asked for changes no planner has read yet, so that asking again is said as such. */
    asked?: boolean
    /** The caller's own word on the plan, such as Approve, at the start of the bar under it. */
    actions?: ReactNode
    /** What the caller says about those, under them in the bar: what they will do, or what one did. */
    actionsNote?: ReactNode
    /** The plan this one replaces, by its name and Markdown, to show what changed since (`src/lib/plan-diff.ts`). */
    previous?: { label: string; markdown: string } | undefined
}) {
    const editor = useEditor({
        extensions: planExtensions([
            PlanHighlights,
            PlanChanges,
            // An empty plan says what goes in it rather than show a blank box (`.plan-doc` in src/index.css).
            Placeholder.configure({ placeholder: 'Write the plan here, or paste its Markdown.' }),
        ]),
        content: markdown,
        contentType: 'markdown',
        editable,
        // The editor renders on the first pass, so the plan never paints empty first.
        immediatelyRender: true,
        // Pasted Markdown is read whole (`src/lib/plan-schema.ts`), so the marks' own paste rules would add nothing but
        // turn a Shift paste's `**bold**` bold. Typed Markdown (`## `, `**`) still formats, by the input rules.
        enablePasteRules: false,
        // What a render shows is selected below (`useEditorState`), so a keystroke re-renders only what it changes.
        shouldRerenderOnTransaction: false,
        editorProps: {
            // What the editor scrolls into view (the cursor as it types, a passage shown from its comment) stays clear
            // of the toolbar, which sticks over the top of the page.
            scrollMargin: { top: TOOLBAR_CLEARANCE, bottom: BAR_CLEARANCE, left: 0, right: 0 },
            scrollThreshold: { top: TOOLBAR_CLEARANCE, bottom: BAR_CLEARANCE, left: 0, right: 0 },
            attributes: {
                class: 'plan-doc',
                'aria-label': 'Plan',
                'aria-multiline': 'true',
                role: 'textbox',
            },
        },
    })
    const [draft, setDraft] = useState<Draft | undefined>(undefined)
    // Whether the plan here says other than it did when it opened, by the editor's own Markdown for both: the planner's
    // may be written otherwise (`*` for `-`), and an edit undone can leave an empty paragraph at the end, neither of
    // which the operator wrote.
    const [original] = useState(() => editor.getMarkdown().trimEnd())
    const [changed, setChanged] = useState(false)
    // Whether the words changed since the plan this one replaces are drawn over it.
    const [showChanges, setShowChanges] = useState(false)
    const seen = useEditorState({
        editor,
        selector: ({ editor: current }) => {
            const highlights = highlightsKey.getState(current.state)
            return {
                // Where each found thread starts, in plan order: what the list's order and its `passage gone` follow.
                starts: [...(highlights?.ranges ?? new Map<string, Range>())].map(([id, range]) => [id, range.from]),
                active: highlights?.active,
                // Where the comment being written starts, which places it among the threads.
                draftFrom: highlights?.draft?.from,
                selected: !current.state.selection.empty,
            }
        },
    })
    const starts = new Map(seen.starts as [string, number][])
    const ordered = inPlanOrder(threads, starts)
    const draftFrom = seen.draftFrom
    const draftAt =
        draftFrom === undefined
            ? 0
            : ordered.filter((thread) => !thread.resolved && (starts.get(thread.id) ?? Infinity) < draftFrom).length
    const list = useRef<HTMLDivElement>(null)
    // Whether the comments sit beside the plan, as `alignComments` last found them.
    const [beside, setBeside] = useState(true)
    // The thread opened from its passage, which floats there while the comments sit under the plan.
    const [clicked, setClicked] = useState<string | undefined>(undefined)
    if (clicked !== undefined && clicked !== seen.active) {
        // Closed, or another thread opened: the caret coming back to that passage opens it in the list, not afloat.
        setClicked(undefined)
    }
    // Under the plan, the comment being written, and a thread opened from its passage while it stays open, float
    // under their passage (`floatUnder`), so the page need not go down to the list and back.
    const draftFloats = !beside && draft !== undefined
    const floating = beside || clicked === undefined ? undefined : threads.find((thread) => thread.id === clicked)
    const frame = useRef<HTMLDivElement>(null)
    const float = useRef<HTMLDivElement>(null)

    // Each comment beside its passage while the comments sit beside the plan (`src/lib/plan-margin.ts`), or the one
    // floating under its passage while they do not: after each render, and whenever an edit, a resize, or a card that
    // grows (a reply being written) moves a passage or a card.
    const place = useEffectEvent(() => {
        const highlights = highlightsKey.getState(editor.state)
        const range = draftFloats ? highlights?.draft : floating && highlights?.ranges.get(floating.id)
        if (float.current !== null && frame.current !== null && range !== undefined) {
            floatUnder(editor, range, float.current, frame.current)
        }
    })
    useLayoutEffect(() => {
        if (list.current !== null) {
            alignComments(editor, list.current)
        }
        place()
    })
    useEffect(() => {
        const element = list.current
        if (element === null) {
            return
        }
        const align = () => {
            setBeside(alignComments(editor, element))
            place()
        }
        const observer = new ResizeObserver(align)
        observer.observe(element)
        observer.observe(editor.view.dom)
        editor.on('transaction', align)
        return () => {
            observer.disconnect()
            editor.off('transaction', align)
        }
    }, [editor])

    // The threads go to the highlights whenever they change; the plugin keeps the ranges it has and looks for the rest.
    useEffect(() => {
        const placed = threads.map(({ id, anchor, resolved }) => ({ id, anchor, resolved }))
        const tr = withHighlight(editor.state.tr, { kind: 'sync', threads: placed }).setMeta('addToHistory', false)
        editor.view.dispatch(tr)
    }, [editor, threads])

    useEffect(() => {
        editor.setEditable(editable)
    }, [editor, editable])

    // The plan this one replaces, read as the editor reads a plan, while its changes are shown; none while not.
    const base = showChanges && previous !== undefined ? previous.markdown : undefined
    useEffect(() => {
        const text = base === undefined ? undefined : textOf(editor, base)
        editor.view.dispatch(editor.state.tr.setMeta(changesKey, { base: text }).setMeta('addToHistory', false))
    }, [editor, base])

    // After an edit, the threads' passages may have moved or changed their words: save their anchors as they are now.
    const onEdit = useEffectEvent(() => {
        const next = withAnchors(threads, anchorsOf(editor.state).anchors)
        if (next !== threads) {
            onThreadsChange(next)
        }
        const now = editor.getMarkdown()
        setChanged(now.trimEnd() !== original)
        onChange?.(now)
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
        const range = highlightsKey.getState(editor.state)?.draft
        setDraft(undefined)
        editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'draft', range: undefined }))
        backToPlan(range)
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
        backToPlan(range)
    }

    // Puts the cursor back in the plan after `range`, a comment's passage, as a shared document does once a comment is
    // sent, resolved, or put aside: the keyboard carries on in the plan rather than from the top of the page, where the
    // focus falls when the control that had it goes. With no passage, the plan takes the focus where its cursor was.
    function backToPlan(range: Range | undefined) {
        if (range === undefined) {
            editor.commands.focus()
        } else {
            editor.commands.focus(range.to)
        }
    }

    // What the operator did to thread `id` from its card, then the cursor back after its passage: looked up first, as
    // a thread deleted takes its passage with it.
    function onThread(id: string, next: PlanThread[]) {
        const range = highlightsKey.getState(editor.state)?.ranges.get(id)
        onThreadsChange(next)
        backToPlan(range)
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
        } else if (!fromCard && !beside) {
            // Under the plan, the card floats at its passage rather than send the page down to it.
            setClicked(id)
        } else if (!fromCard) {
            // The thread's card, not its highlight in the plan, which carries the same attribute.
            document.querySelector(`article[data-thread="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' })
        }
    }

    const open = threads.filter((thread) => !thread.resolved).length
    const threadActions: ThreadActions = {
        onActivate: (id) => activate(id, true),
        onOpen: (id) => editor.view.dispatch(withHighlight(editor.state.tr, { kind: 'activate', id })),
        onReply: (id, body) =>
            onThread(id, addReply(threads, id, { id: crypto.randomUUID(), body, at: new Date().toISOString() })),
        onResolve: (id, resolved) => onThread(id, setResolved(threads, id, resolved)),
        onDelete: (id) => onThread(id, removeThread(threads, id)),
        onEdit: (id, body, replyId) =>
            onThread(id, replyId === undefined ? editThread(threads, id, body) : editReply(threads, id, replyId, body)),
        onBack: (id) => backToPlan(highlightsKey.getState(editor.state)?.ranges.get(id)),
    }
    const onDraftChange = (body: string) => setDraft(draft && { ...draft, body })
    const onDraftLeave = () => backToPlan(highlightsKey.getState(editor.state)?.draft)
    return (
        // The comments sit beside the plan once both fit (a 20rem column beside a plan of about 40rem), by the space
        // the page gives them rather than the window's width, since the rail takes some of it. The plan's column
        // stops at its text's measure (`.plan-doc`'s 48rem and the panel's padding), so on a wide page the comments
        // stay against the text, as a shared document's margin does, and the room left over goes after them.
        <div ref={frame} className="@container relative min-w-0">
            <div className="grid min-w-0 items-start gap-6 @min-[60rem]:grid-cols-[minmax(0,51rem)_20rem]">
                <Panel>
                    <PanelHeader label="Plan" sticky>
                        {editable && <FormatBar editor={editor} canComment={seen.selected} onComment={startComment} />}
                    </PanelHeader>
                    <EditorContent editor={editor} className="px-6 py-4" />
                    {editable && (
                        <BubbleMenu
                            editor={editor}
                            pluginKey={BUBBLE}
                            // Fixed, so a bubble over a passage below the window never makes the window scroll: the
                            // window would scroll back as the bubble hides, under a click on the toolbar's Comment.
                            options={{ placement: 'top', strategy: 'fixed' }}
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
                        draft={draftFloats ? undefined : draft}
                        draftAt={draftAt}
                        hidden={floating?.id}
                        listRef={list}
                        editable={editable}
                        onDraftChange={onDraftChange}
                        onDraftSubmit={addComment}
                        onDraftCancel={cancelComment}
                        onDraftLeave={onDraftLeave}
                        onResolveGone={() =>
                            onThreadsChange(
                                threads.map((thread) =>
                                    thread.resolved || starts.has(thread.id) ? thread : { ...thread, resolved: true },
                                ),
                            )
                        }
                        {...threadActions}
                    />
                </Panel>
            </div>
            {editable && (actions !== undefined || onAskForChanges !== undefined || previous !== undefined) && (
                // The plan's actions stay at the bottom of the page while it scrolls, as a document's do, so a long
                // plan is approved or sent back from where it is read rather than from under its last line.
                <div
                    data-testid="plan-bar"
                    className={cn(
                        'sticky bottom-0 z-10 mt-3 flex min-h-12 flex-wrap items-center gap-2 rounded-md border',
                        'bg-surface px-3 py-2',
                    )}
                >
                    {previous !== undefined && (
                        // A mode, named for what it shows: the plan as it reads now, with what changed marked on it.
                        <Toggle size="xs" pressed={showChanges} onPressedChange={setShowChanges}>
                            Changes since {previous.label}
                        </Toggle>
                    )}
                    {actions}
                    {onAskForChanges !== undefined && (
                        <AskForChanges
                            threads={threads}
                            starts={starts}
                            edited={edited || changed}
                            asked={asked}
                            onAsk={onAskForChanges}
                        />
                    )}
                    {actionsNote !== undefined && <div className="basis-full">{actionsNote}</div>}
                </div>
            )}
            {draftFloats && (
                <div ref={float} data-testid="plan-float" className={cn(FLOAT, 'bg-accent/14 px-3 py-2.5')}>
                    <DraftForm
                        draft={draft}
                        onDraftChange={onDraftChange}
                        onDraftSubmit={addComment}
                        onDraftCancel={cancelComment}
                        onDraftLeave={onDraftLeave}
                    />
                </div>
            )}
            {!draftFloats && floating !== undefined && (
                <div ref={float} data-testid="plan-float" className={FLOAT}>
                    <ThreadCard thread={floating} lost={false} active editable={editable} {...threadActions} />
                </div>
            )}
        </div>
    )
}

// The block a paragraph is, as the text style group names it.
type BlockStyle = 'paragraph' | 'h1' | 'h2' | 'h3' | 'h4'
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

// Each style shows in the menu as the plan sets it (`.plan-doc` in src/index.css), so the menu previews it.
const STYLES: { name: BlockStyle; label: string; keys: string; preview: string }[] = [
    { name: 'paragraph', label: 'Text', keys: 'Mod-Alt-0', preview: 'text-sm' },
    { name: 'h1', label: 'Heading 1', keys: 'Mod-Alt-1', preview: 'text-xl font-semibold tracking-tight' },
    { name: 'h2', label: 'Heading 2', keys: 'Mod-Alt-2', preview: 'text-base font-semibold' },
    { name: 'h3', label: 'Heading 3', keys: 'Mod-Alt-3', preview: 'text-sm font-semibold' },
    { name: 'h4', label: 'Heading 4', keys: 'Mod-Alt-4', preview: 'text-sm font-semibold' },
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
            inTable: current.isActive('table'),
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
            case 'h3':
            case 'h4': {
                chain.setHeading({ level: Number(name.slice(1)) as 1 | 2 | 3 | 4 }).run()
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
            <StyleMenu style={state.style} onStyle={setStyle} />
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
            <TableMenu editor={editor} inTable={state.inTable} />
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

// The paragraph's style, as a menu that names the one in force, as a document's style menu does: each style shown as
// the plan sets it, with its shortcut. A style chosen leaves the cursor in the plan, where the menu put it; Escape
// takes the focus back to the menu's button.
function StyleMenu({ style, onStyle }: { style: BlockStyle | undefined; onStyle: (style: BlockStyle) => void }) {
    const [chose, setChose] = useState(false)
    const current = STYLES.find((item) => item.name === style)
    return (
        <DropdownMenu
            onOpenChange={(open) => {
                if (open) {
                    setChose(false)
                }
            }}
        >
            <DropdownMenuTrigger asChild>
                <ToolbarButton
                    size="xs"
                    aria-label={`Text style: ${current?.label ?? 'none'}`}
                    title="Text style"
                    className="min-w-24 justify-between"
                >
                    {current?.label ?? 'Text style'}
                    <ChevronDown aria-hidden />
                </ToolbarButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                align="start"
                onCloseAutoFocus={(event) => {
                    if (chose) {
                        event.preventDefault()
                    }
                }}
            >
                <DropdownMenuRadioGroup
                    value={style ?? ''}
                    onValueChange={(value) => {
                        const chosen = STYLES.find((item) => item.name === value)
                        if (chosen !== undefined) {
                            setChose(true)
                            onStyle(chosen.name)
                        }
                    }}
                >
                    {STYLES.map((item) => (
                        <DropdownMenuRadioItem
                            key={item.name}
                            value={item.name}
                            aria-keyshortcuts={ariaKeys(item.keys, APPLE)}
                            className="justify-between gap-6"
                        >
                            <span className={item.preview}>{item.label}</span>
                            <span aria-hidden className="font-mono text-2xs text-muted-foreground">
                                {keysLabel(item.keys, APPLE)}
                            </span>
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

// What the table menu does: insert a table where none is, and inside one, add or delete its rows and columns, or the
// table. Each runs on the editor and leaves the cursor there.
type TableAction =
    | 'insert'
    | 'rowBefore'
    | 'rowAfter'
    | 'columnBefore'
    | 'columnAfter'
    | 'deleteRow'
    | 'deleteColumn'
    | 'deleteTable'

// The menu's items, in its groups, each with what it needs: a table to work in, or none.
const TABLE_ITEMS: { action: TableAction; label: string; inTable: boolean }[][] = [
    [{ action: 'insert', label: 'Insert table', inTable: false }],
    [
        { action: 'rowBefore', label: 'Add row above', inTable: true },
        { action: 'rowAfter', label: 'Add row below', inTable: true },
        { action: 'columnBefore', label: 'Add column left', inTable: true },
        { action: 'columnAfter', label: 'Add column right', inTable: true },
    ],
    [
        { action: 'deleteRow', label: 'Delete row', inTable: true },
        { action: 'deleteColumn', label: 'Delete column', inTable: true },
        { action: 'deleteTable', label: 'Delete table', inTable: true },
    ],
]

// A plan's tables, as a menu: a new one is three columns of a header row and two rows, as a plan's Files table is,
// and inside one its rows and columns are added and deleted. What the cursor's place does not allow is disabled. As
// the style menu does, an action leaves the cursor in the plan, and Escape gives the focus back to the button.
function TableMenu({ editor, inTable }: { editor: Editor; inTable: boolean }) {
    const [chose, setChose] = useState(false)

    function run(action: TableAction) {
        const chain = editor.chain().focus()
        switch (action) {
            case 'insert': {
                chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
                break
            }
            case 'rowBefore': {
                chain.addRowBefore().run()
                break
            }
            case 'rowAfter': {
                chain.addRowAfter().run()
                break
            }
            case 'columnBefore': {
                chain.addColumnBefore().run()
                break
            }
            case 'columnAfter': {
                chain.addColumnAfter().run()
                break
            }
            case 'deleteRow': {
                chain.deleteRow().run()
                break
            }
            case 'deleteColumn': {
                chain.deleteColumn().run()
                break
            }
            case 'deleteTable': {
                chain.deleteTable().run()
                break
            }
            default: {
                action satisfies never
            }
        }
    }

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                if (open) {
                    setChose(false)
                }
            }}
        >
            <DropdownMenuTrigger asChild>
                <ToolbarButton aria-label="Table" title="Table">
                    <Table />
                </ToolbarButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                align="end"
                onCloseAutoFocus={(event) => {
                    if (chose) {
                        event.preventDefault()
                    }
                }}
            >
                {TABLE_ITEMS.map((group, i) => (
                    <Fragment key={group[0]?.action}>
                        {i > 0 && <DropdownMenuSeparator />}
                        {group.map((item) => (
                            <DropdownMenuItem
                                key={item.action}
                                disabled={item.inTable !== inTable}
                                onSelect={() => {
                                    setChose(true)
                                    run(item.action)
                                }}
                            >
                                {item.label}
                            </DropdownMenuItem>
                        ))}
                    </Fragment>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

// The style of the paragraph at the cursor, or undefined in a block the menu does not name (a code block).
function styleAt(editor: Editor): BlockStyle | undefined {
    for (const level of [1, 2, 3, 4] as const) {
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
