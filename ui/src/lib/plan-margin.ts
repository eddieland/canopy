// The comments beside a plan, each card at the height of its passage, as a shared document's margin has them
// (docs/design/PLANNING.md §25, Commenting on a plan). Cards keep the order the plan reads, so where two passages sit
// close, the later card moves down to clear the earlier one; the card that is open, or the comment being written, sits
// exactly at its passage, and the cards before it move up to make room. The cards stay in the column's flow: each is
// placed by its top margin, so what follows them (comments whose passage is gone, the resolved ones, Ask for changes)
// comes after the last. Below the width where the column sits beside the plan, the cards are a plain list again, and
// the comment being written, or a thread opened from its passage, floats under its passage instead (`floatUnder`).
import type { Editor } from '@tiptap/core'

import { highlightsKey } from '@/lib/plan-highlights'
import type { Range } from '@/lib/plan-highlights'

/** The space between two cards that would otherwise touch, in pixels. */
export const GAP = 8

/** A card to place: where its passage starts, from the top of the column, and how tall it is. */
export interface Card {
    /** Where the card would sit if nothing were in its way: its passage's top. */
    want: number
    /** The card's height. */
    height: number
}

/**
 * Where each card's top goes, in the order given (the plan's): each as near its passage as the cards before it allow,
 * `gap` apart, and none above the column's top. With an `anchor`, that card sits at its passage, and those before it
 * move up as far as they must to make room, then down again only if they would leave the column.
 */
export function stack(cards: Card[], anchor: number | undefined, gap = GAP): number[] {
    const tops = cards.map((card) => card.want)
    if (anchor !== undefined && anchor >= 0 && anchor < cards.length) {
        for (let i = anchor - 1; i >= 0; i -= 1) {
            tops[i] = Math.min(tops[i] ?? 0, (tops[i + 1] ?? 0) - gap - (cards[i]?.height ?? 0))
        }
    }
    for (let i = 0; i < tops.length; i += 1) {
        const floor = i === 0 ? 0 : (tops[i - 1] ?? 0) + (cards[i - 1]?.height ?? 0) + gap
        tops[i] = Math.max(tops[i] ?? 0, floor)
    }
    return tops
}

/**
 * Places the cards in `list` beside their passages in `editor`, when the list sits beside the plan, and puts them back
 * in a plain list when it does not. A card to place carries `data-align`: its thread's id, or `draft` for the comment
 * being written, and they come first in the list, in the plan's order. The open one carries `data-active`. Whether the
 * list sits beside the plan.
 */
export function alignComments(editor: Editor, list: HTMLElement): boolean {
    const cards = [...list.children].filter(
        (child): child is HTMLElement => child instanceof HTMLElement && child.dataset['align'] !== undefined,
    )
    for (const card of cards) {
        card.style.marginTop = ''
    }
    const plan = editor.view.dom.getBoundingClientRect()
    const column = list.getBoundingClientRect()
    const highlights = highlightsKey.getState(editor.state)
    const beside = column.left >= plan.right
    // The cards are drawn as cards of their own only while they sit apart (`.plan-margin` in src/index.css).
    list.toggleAttribute('data-aligned', beside)
    if (cards.length === 0 || !beside || highlights === undefined) {
        return beside
    }
    const placed: Card[] = []
    for (const card of cards) {
        const id = card.dataset['align'] ?? ''
        const range = id === 'draft' ? highlights.draft : highlights.ranges.get(id)
        const want = range === undefined ? 0 : editor.view.coordsAtPos(range.from).top - column.top
        placed.push({ want, height: card.offsetHeight })
    }
    const anchor = cards.findIndex((card) => card.dataset['align'] === 'draft' || card.dataset['active'] === 'true')
    const tops = stack(placed, anchor === -1 ? undefined : anchor)
    let bottom = 0
    cards.forEach((card, i) => {
        const top = tops[i] ?? 0
        card.style.marginTop = `${top - bottom}px`
        bottom = top + (placed[i]?.height ?? 0)
    })
    return beside
}

/**
 * Puts the cards in `list` back in a plain list, as `alignComments` does when the list does not sit beside the plan:
 * for while the plan shows as Markdown, with no passages on the page to place them by.
 */
export function releaseComments(list: HTMLElement): void {
    for (const card of list.children) {
        if (card instanceof HTMLElement) {
            card.style.marginTop = ''
        }
    }
    delete list.dataset['aligned']
}

/**
 * Places `card` under the passage `range` covers in `editor`, inside `container`, which it is positioned in: its top
 * `GAP` under the passage's last line, its left at the passage's start, kept within the container's sides. For a
 * comment shown at its passage while the comments sit under the plan, so the page need not go to them.
 */
export function floatUnder(editor: Editor, range: Range, card: HTMLElement, container: HTMLElement): void {
    const box = container.getBoundingClientRect()
    const start = editor.view.coordsAtPos(range.from)
    const end = editor.view.coordsAtPos(range.to)
    const widest = box.width - card.offsetWidth - GAP
    card.style.top = `${end.bottom - box.top + GAP}px`
    card.style.left = `${Math.max(0, Math.min(start.left - box.left, widest))}px`
}
