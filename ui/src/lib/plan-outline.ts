// A plan's outline: its headings, in order, as the plan editor's Outline menu lists them
// (src/components/plan-editor.tsx), so a long plan is read and reread by its sections. A planner writes every plan to
// the same headings (.agents/prompts/worker-plan.md), so the outline is the same skeleton from one plan to the next;
// one the operator edited lists what it holds now.
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'

/** One heading of a plan, as its outline lists it. */
export interface OutlineEntry {
    /** Its level, as its Markdown says it: 1 for `#`. */
    level: number
    /** How far the outline indents it: 0 for the plan's shallowest heading, one more for each level under it. */
    depth: number
    /** Its words, their whitespace collapsed. */
    text: string
    /** Where it starts in the document. */
    pos: number
}

/**
 * The headings at the top of a plan's document, in order. A heading inside another block (a quote, a list) heads no
 * section of the plan, and one with no words names none, so neither is listed.
 */
export function planOutline(doc: ProseMirrorNode): OutlineEntry[] {
    const found: OutlineEntry[] = []
    doc.forEach((node, pos) => {
        const text = node.textContent.replaceAll(/\s+/gu, ' ').trim()
        if (node.type.name === 'heading' && text !== '') {
            found.push({ level: Number(node.attrs['level']), depth: 0, text, pos })
        }
    })
    const top = Math.min(...found.map((entry) => entry.level))
    for (const entry of found) {
        entry.depth = entry.level - top
    }
    return found
}

/**
 * Which section is being read, by where each heading's top is on the page and the line under the page's sticky header:
 * the last heading at or above that line, or the first while every heading is still below it. Undefined with none.
 */
export function sectionAt(tops: readonly number[], line: number): number | undefined {
    if (tops.length === 0) {
        return undefined
    }
    const passed = tops.findLastIndex((top) => top <= line)
    return passed === -1 ? 0 : passed
}
