import { useSyncExternalStore } from 'react'

import { sectionAt } from '@/lib/plan-outline'

// How far under the top of the page's scroll the line sits that a heading passes to become the one read, in pixels:
// past a heading's scroll margin, so a heading gone to is over the line.
const LINE = 96

/**
 * Which of the headings `ids` names (space-separated, in page order) is being read, as the page scrolls: the last
 * whose top has passed the line near the top of the page's scroll, or the first while all are still below it. Near
 * the page's end a late heading never reaches that line, so the heading `went` names, the one last gone to, is the one
 * read while it is on screen and the line is still above it, and at the very end the last heading is. Undefined with
 * no heading on the page.
 */
export function useSectionRead(ids: string, went?: string): string | undefined {
    return useSyncExternalStore(subscribe, () => sectionRead(ids, went))
}

function subscribe(changed: () => void): () => void {
    // Scroll events do not bubble: caught on their way down, whichever element the page scrolls in.
    document.addEventListener('scroll', changed, { capture: true, passive: true })
    globalThis.addEventListener('resize', changed)
    return () => {
        document.removeEventListener('scroll', changed, { capture: true })
        globalThis.removeEventListener('resize', changed)
    }
}

function sectionRead(ids: string, went: string | undefined): string | undefined {
    const headings = ids
        .split(' ')
        .map((id) => (id === '' ? null : document.querySelector(`#${CSS.escape(id)}`)))
        .filter((heading) => heading !== null)
    const scroller = headings[0]?.closest('.page-scroll')
    const top = scroller?.getBoundingClientRect().top ?? 0
    const bottom = scroller?.getBoundingClientRect().bottom ?? globalThis.innerHeight
    const boxes = headings.map((heading) => heading.getBoundingClientRect())
    const passed = sectionAt(
        boxes.map((box) => box.top),
        top + LINE,
    )
    if (passed === undefined) {
        return undefined
    }
    const gone = headings.findIndex((heading) => heading.id === went)
    const box = boxes[gone]
    if (box !== undefined && gone > passed && box.top >= top && box.bottom <= bottom) {
        return went
    }
    const ended =
        scroller !== null &&
        scroller !== undefined &&
        scroller.scrollTop > 0 &&
        scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 1
    return (ended ? headings.at(-1) : headings[passed])?.id
}
