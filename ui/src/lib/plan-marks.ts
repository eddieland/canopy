// A plan's section marks: the operator marks each `##` section of a ticket's plan read, or read with a concern, so a
// long plan shows what is left to read (the Outline menu, src/components/plan-editor.tsx). A mark is a note to the
// operator alone: it sends nothing to the planner, which comments do. It is this browser's, in localStorage and synced
// across tabs, never the journal, as the tickets viewed are (src/lib/recent-tickets.ts). A mark holds while its section
// reads as it did when it was marked, by a digest of its words, so a new plan's section the planner rewrote, or one the
// operator edited, is unread again, and one left as it was keeps its mark.
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'

import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/** How a section is marked: read and fine, or read with a concern to come back to. */
export type SectionMark = 'read' | 'concern'

/** One section of a plan, as it can be marked. */
export interface PlanSection {
    /** Its heading's words, then ` #2` and on for a heading an earlier section has too: what its mark is kept by. */
    key: string
    /** Where its heading starts in the document, as its outline entry's `pos`. */
    pos: number
    /** A digest of its words under the heading, to the next section: a mark holds while it is the same. */
    digest: string
}

/** A section's mark, as kept. */
export interface StoredMark {
    /** How it is marked. */
    mark: SectionMark
    /** Its section's digest when it was marked. */
    digest: string
}

/** A ticket's marks, as kept. */
export interface TicketMarks {
    /** When one was last set or cleared, ISO: the oldest ticket past `MARKS_MAX` is dropped. */
    at: string
    /** Each section's mark, by its key. */
    sections: Record<string, StoredMark>
}

/** Every ticket's marks, by its key. */
export type PlanMarks = Record<string, TicketMarks>

/** Where localStorage keeps the marks. */
export const STORAGE_KEY = 'canopy-plan-marks'
/** How many tickets' marks are kept: those marked last. */
export const MARKS_MAX = 50
/** The level of a plan's sections: `##`, as the planner writes them (.agents/prompts/worker-plan.md). */
export const SECTION_LEVEL = 2

/**
 * The sections of a plan's document: each `##` heading at its top, with the blocks under it up to the next heading of
 * its level or above, so Steps holds its steps. A heading with no words names no section.
 */
export function planSections(doc: ProseMirrorNode): PlanSection[] {
    const found: { text: string; pos: number; body: string[] }[] = []
    // The words of the section open, none before the first or after a heading that ends one without opening another.
    let body: string[] | undefined = undefined
    doc.forEach((node, pos) => {
        const level = node.type.name === 'heading' ? Number(node.attrs['level']) : undefined
        if (level !== undefined && level <= SECTION_LEVEL) {
            const text = node.textContent.replaceAll(/\s+/gu, ' ').trim()
            body = level === SECTION_LEVEL && text !== '' ? [] : undefined
            if (body !== undefined) {
                found.push({ text, pos, body })
            }
            return
        }
        body?.push(node.textContent)
    })
    const seen = new Map<string, number>()
    return found.map(({ text, pos, body: words }) => {
        const n = (seen.get(text) ?? 0) + 1
        seen.set(text, n)
        return { key: n === 1 ? text : `${text} #${n}`, pos, digest: digestOf(words.join('\n')) }
    })
}

/** The marks that still hold on `sections`, by section key: each whose section reads as it did when it was marked. */
export function marksOn(marks: TicketMarks | undefined, sections: readonly PlanSection[]): Map<string, SectionMark> {
    const holding = new Map<string, SectionMark>()
    for (const section of sections) {
        const stored =
            marks !== undefined && Object.hasOwn(marks.sections, section.key) ? marks.sections[section.key] : undefined
        if (stored?.digest === section.digest) {
            holding.set(section.key, stored.mark)
        }
    }
    return holding
}

/**
 * `marks` with ticket `ticket`'s section marked `mark` at `at`, or its mark cleared with none, the ticket dropped once
 * it has none left; the oldest tickets past `MARKS_MAX` are dropped.
 */
export function withMark(
    marks: PlanMarks,
    ticket: string,
    section: PlanSection,
    mark: SectionMark | undefined,
    at: string,
): PlanMarks {
    const sections = { ...(Object.hasOwn(marks, ticket) ? marks[ticket]?.sections : undefined) }
    if (mark === undefined) {
        delete sections[section.key]
    } else {
        sections[section.key] = { mark, digest: section.digest }
    }
    const rest = Object.entries(marks).filter(([key]) => key !== ticket)
    const kept = Object.keys(sections).length > 0 ? [[ticket, { at, sections }] as const, ...rest] : rest
    const newest = kept.toSorted(([, a], [, b]) => b.at.localeCompare(a.at)).slice(0, MARKS_MAX)
    return Object.fromEntries(newest)
}

/** The marks as stored, or none for anything that is not: each ticket or mark that is not one is dropped. */
export function parseMarks(raw: string | null): PlanMarks {
    let value: unknown
    try {
        value = JSON.parse(raw ?? '{}')
    } catch {
        return {}
    }
    if (!isRecord(value)) {
        return {}
    }
    const marks: PlanMarks = {}
    for (const [ticket, entry] of Object.entries(value)) {
        if (isRecord(entry) && typeof entry['at'] === 'string' && isRecord(entry['sections'])) {
            const sections = Object.fromEntries(
                Object.entries(entry['sections']).filter((pair): pair is [string, StoredMark] => isMark(pair[1])),
            )
            marks[ticket] = { at: entry['at'], sections }
        }
    }
    return marks
}

/** Ticket `ticket`'s marks, none without one. Re-renders on a change from this tab or another. */
export function usePlanMarks(ticket: string | undefined): TicketMarks | undefined {
    const marks = useStoredSetting(setting)
    return ticket !== undefined && Object.hasOwn(marks, ticket) ? marks[ticket] : undefined
}

/** Marks ticket `ticket`'s section `mark`, or clears its mark with none, stores it, and applies it now. */
export function markSection(ticket: string, section: PlanSection, mark: SectionMark | undefined): void {
    setting.set(withMark(setting.get(), ticket, section, mark, new Date().toISOString()))
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseMarks, serialize: (value) => JSON.stringify(value) })

// A short digest of a section's words (FNV-1a, 32 bits): enough to tell a section rewritten from one left as it was,
// and small enough that a ticket's marks take a few bytes each, however long its Steps.
function digestOf(text: string): string {
    // FNV-1a's offset basis and prime, in decimal, which the formatter and the lint agree on.
    let hash = 2_166_136_261
    for (let i = 0; i < text.length; i += 1) {
        hash = Math.imul(hash ^ (text.codePointAt(i) ?? 0), 16_777_619)
    }
    return (hash >>> 0).toString(36)
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isMark(value: unknown): value is StoredMark {
    return (
        isRecord(value) &&
        (value['mark'] === 'read' || value['mark'] === 'concern') &&
        typeof value['digest'] === 'string'
    )
}
