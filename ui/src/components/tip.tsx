import { useRef, useState } from 'react'
import type { ComponentProps, PointerEvent, ReactElement, ReactNode } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useCut } from '@/hooks/use-cut'
import { cn } from '@/lib/utils'

// What a tip's trigger cannot be its own stop inside. Inside a control the keyboard already stops on the control,
// which names what it holds, and a stop in it would be a control in a control; inside an element with a `title` of
// its own, the browser would show that title over the tip.
const ENCLOSING = 'a[href], button, summary, label, [role="button"], [role="link"], [title]'

/**
 * A fact about what it wraps that has no room on the page (ui/DESIGN.md, "A fact on hover is a tip"): a word's CLI
 * spelling, an age's local time, a cut title whole. It opens on hover, on the keyboard's focus, and on a tap, so the
 * mouse, the keyboard, and a touch screen all reach it, and its child, one element, becomes a stop for the keyboard.
 * With no fact it is its child alone. Inside a link or a button, which is the keyboard's stop already, or inside an
 * element with a `title`, the fact is the child's own `title`, as it was before tips. `mono` sets the fact in
 * monospace, as the CLI prints it. `detail` goes on a line of its own under the fact, in the page's font: what a word
 * the fact spells means.
 */
export function Tip({
    fact,
    mono = false,
    detail,
    children,
}: {
    fact: string | null | undefined
    mono?: boolean
    detail?: string | null
    children: ReactElement
}) {
    const [open, setOpen] = useState(false)
    const [nested, setNested] = useState(false)
    // Whether it was open when a touch began, so a tap toggles it: Radix's trigger closes it on any press.
    const touched = useRef<boolean | null>(null)
    const trigger = useRef<HTMLElement | null>(null)
    // Set from a focus until two frames have drawn, or until a press or Escape, which are the operator's. Focusing a
    // trigger in a scrolling panel scrolls it into view, and Radix closes an open tooltip when anything around its
    // trigger scrolls; that scroll's event comes a frame after the focus opened the tip, so a close while it settles,
    // with the trigger still focused, is that scroll's.
    const settling = useRef(false)
    const shown = fact === null || fact === undefined || fact === '' ? null : fact
    const place = (element: HTMLElement | null) => {
        trigger.current = element
        if (element !== null) {
            setNested((element.parentElement?.closest(ENCLOSING) ?? null) !== null)
        }
    }
    const own = shown !== null && !nested
    const change = (next: boolean) => {
        if (!next && settling.current && trigger.current !== null && document.activeElement === trigger.current) {
            return
        }
        setOpen(next)
    }
    return (
        <Tooltip open={own && open} onOpenChange={change}>
            <TooltipTrigger
                asChild
                ref={place}
                tabIndex={own ? 0 : undefined}
                title={shown !== null && nested ? [shown, detail].filter(Boolean).join('\n') : undefined}
                onFocus={() => {
                    settling.current = true
                    requestAnimationFrame(() => {
                        requestAnimationFrame(() => {
                            settling.current = false
                        })
                    })
                }}
                onPointerDown={(event: PointerEvent) => {
                    settling.current = false
                    touched.current = event.pointerType === 'touch' ? open : null
                }}
                onClick={(event) => {
                    if (own && touched.current !== null) {
                        event.preventDefault()
                        setOpen(!touched.current)
                    }
                    touched.current = null
                }}
            >
                {children}
            </TooltipTrigger>
            {own && (
                <TooltipContent
                    onEscapeKeyDown={() => {
                        settling.current = false
                    }}
                >
                    <span className={cn(mono && 'font-mono')}>{shown}</span>
                    {detail && `\n${detail}`}
                </TooltipContent>
            )}
        </Tooltip>
    )
}

/**
 * Text cut to fit its place on one line, whole in a `Tip` while it is cut, and only then: a whole title needs no tip,
 * and is no stop for the keyboard. `text` is the whole; `children`, what shows, when it is more than the text (its
 * links).
 */
export function Clipped({
    text,
    mono = false,
    className,
    children,
    ...props
}: Omit<ComponentProps<'span'>, 'ref' | 'title'> & { text: string; mono?: boolean; children?: ReactNode }) {
    const [ref, cut] = useCut()
    return (
        <Tip fact={cut ? text : null} mono={mono}>
            <span ref={ref} className={cn('truncate', className)} {...props}>
                {children ?? text}
            </span>
        </Tip>
    )
}
