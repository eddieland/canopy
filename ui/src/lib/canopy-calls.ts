import type { TranscriptTool } from '@/api/types'
import { pullRequestLabel } from '@/lib/pull-request-label'

/** The color a call's action wears on its line: plain, or that of what waits on the operator. */
export type CallTone = 'plain' | 'blocked'

/** Words of the agent's own a call carries, under the name of the field that held them. */
export interface CallSaid {
    /** The field: `rationale`, `context`, or `detail`. */
    label: string
    /** The words, as written. */
    text: string
}

/**
 * A call of one of canopy's own tools, as its line says it: what it is about, what it does, the rest of what it
 * names, what the agent said with it, and what canopy answered.
 */
export interface CanopyCall {
    /** What the call is about: a ticket, a PR, a chore, a checkout; null when it names none. */
    subject: string | null
    /** What it does to it, as a chip: a run's kind, `wait`, an attention reason; null when its name says it all. */
    action: string | null
    /** The chip's color. */
    tone: CallTone
    /** The rest of what it names, as a command would: revisions, paths, numbers; null when there is none. */
    detail: string | null
    /** The agent's own words with it; null when it gave none. */
    said: CallSaid | null
    /** What canopy answered, in a few words: its own words' first line, or how much it found; null when the call
     * failed or its answer is its output whole. */
    told: string | null
}

/**
 * A call of one of canopy's own tools as its line says it, read from its name, its input, and what canopy answered;
 * null for any other tool's call, and for a tool of canopy's this does not know, whose line is its input's values.
 * canopy names its servers (`canopy`, `canopy_git`, `canopy_reports`, `canopy_chore`) and the runtime joins the
 * tool's own name to them, so a name is read from its start. `decide`, `ticket-set`, a run's `status`, `result`, and
 * `messages` have their own readers in `src/lib/transcript.ts`.
 */
export function canopyCall(entry: TranscriptTool): CanopyCall | null {
    const own = ownName(entry.tool)
    const input = record(parse(entry.input))
    if (own === null || input === null) {
        return null
    }
    // What canopy answered, for a call it took: its words, and the record under them where it answered with one.
    const answer = entry.status === 'error' ? null : entry.output
    const output = answer === null ? null : record(payload(answer))
    // Its own member alone: a tool named for one every object inherits (`constructor`) has no reader.
    const read = Object.hasOwn(READERS, own) ? READERS[own] : undefined
    return read === undefined ? null : { ...BLANK, ...read(input, output, answer) }
}

const BLANK: CanopyCall = { subject: null, action: null, tone: 'plain', detail: null, said: null, told: null }

// The servers canopy names, longest first, each with what its tools' own names are filed under here.
const SERVERS = [
    ['canopy_reports_', 'reports '],
    ['canopy_chore_', 'chore '],
    ['canopy_git_', 'git '],
    ['canopy_', ''],
] as const

// A tool's own name under its server, hyphens for whatever the runtime joined its words with: `git merge-base`.
function ownName(tool: string): string | null {
    for (const [prefix, family] of SERVERS) {
        if (tool.startsWith(prefix)) {
            return `${family}${tool.slice(prefix.length).replaceAll('_', '-')}`
        }
    }
    return null
}

type Fields = Record<string, unknown>
// What reads a call's line: from its input, the record canopy answered with (null when it answered in words, or
// refused), and its answer's text (null when it refused).
type Reader = (input: Fields, output: Fields | null, answer: string | null) => Partial<CanopyCall>

const READERS: Partial<Record<string, Reader>> = {
    dispatch: (input, _, answer) => ({
        subject: text(input['key']),
        action: text(input['kind']),
        detail: joined([list(input['repos']).join(', '), prefixed('on ', text(input['base']))]),
        said: said(input, 'context'),
        told: spoken(answer),
    }),
    attention: (input, _, answer) => ({
        subject: joined([text(input['key']) ?? pr(input['pr']), text(input['repo'])]),
        action: text(input['reason']),
        tone: 'blocked',
        said: said(input, 'detail'),
        told: spoken(answer),
    }),
    'review-items': (input, output) => ({
        subject: unit(input),
        detail: prefixed('items ', list(input['numbers']).join(', ')),
        told: counted(Array.isArray(output?.['items']) ? output['items'].length : null, 'item'),
    }),
    'review-run': (input, _, answer) => ({
        subject: pr(input['pr']),
        action: 'review',
        detail: joined([prefixed('at ', short(input['sha'])), text(input['ticket'])]),
        said: said(input, 'context'),
        told: spoken(answer),
    }),
    'review-wait': (input, _, answer) => ({
        subject: joined([pr(input['pr']), text(input['ticket'])]),
        action: 'wait',
        said: said(input, 'rationale'),
        told: spoken(answer),
    }),
    'review-end': (input, _, answer) => ({
        subject: pr(input['pr']),
        action: text(input['reason']),
        told: spoken(answer),
    }),
    'review-revise': (input, _, answer) => ({
        subject: prefixed('review ', text(input['run'])),
        action: 'revise',
        told: spoken(answer),
    }),
    'chore-run': (input, _, answer) => ({
        subject: text(input['name']),
        action: 'run',
        said: said(input, 'context'),
        told: spoken(answer),
    }),
    'chore-wait': (input, _, answer) => ({
        subject: text(input['name']),
        action: 'wait',
        said: said(input, 'rationale'),
        told: spoken(answer),
    }),
    'chore history': (input) => ({
        subject: text(input['name']),
        detail:
            prefixed('run ', text(input['run'])) ??
            joined([prefixed('last ', text(input['limit'])), prefixed('before run ', text(input['before']))]),
    }),
    'git merge-base': (input) => ({
        subject: text(input['repo']),
        detail: joined([text(input['base']), text(input['head'])]),
    }),
    'git diff': (input) => ({
        subject: text(input['repo']),
        action: input['stat'] === true ? 'stat' : null,
        detail: joined([`${text(input['base']) ?? ''}..${text(input['head']) ?? ''}`, paths(input)]),
    }),
    'git log': (input, output) => ({
        subject: text(input['repo']),
        detail: joined([
            text(input['range']),
            paths(input),
            prefixed('changing ', quoted(input['search'])),
            prefixed('saying ', quoted(input['message'])),
        ]),
        told: more(counted(Array.isArray(output?.['commits']) ? output['commits'].length : null, 'commit'), output),
    }),
    'git show': (input) => ({ subject: text(input['repo']), detail: at(input) }),
    'git blame': (input) => ({
        subject: text(input['repo']),
        detail: joined([at(input), lines(input['start'], input['end'])]),
    }),
    'git grep': (input, output) => ({
        subject: text(input['repo']),
        action: input['count'] === true ? 'count' : null,
        detail: joined([
            quoted(input['text']),
            // What changes how the text is read, so a pattern never passes for the words it holds.
            input['regex'] === true ? 'as a regex' : null,
            input['word'] === true ? 'whole words' : null,
            input['ignore_case'] === true ? 'any case' : null,
            prefixed('at ', text(input['rev'])),
            paths(input),
        ]),
        told: more(found(output), output),
    }),
    'git files': (input) => ({
        subject: text(input['repo']),
        detail: joined([text(input['rev']), prefixed('named ', quoted(input['name'])), paths(input)]),
    }),
    'reports health': (input) => ({ detail: days(input) }),
    'reports spend': (input) => ({ detail: days(input) }),
    'reports memory-lessons': (input) => ({ subject: text(input['repo']) }),
    'reports memory-list': (input) => ({
        subject: text(input['key']),
        detail: input['all'] === true ? 'superseded too' : null,
    }),
    'reports waiting': (input) => ({ detail: prefixed('since ', text(input['since'])) }),
}

// A string or a number as text; null for anything else, and for an empty string.
function text(value: unknown): string | null {
    if (typeof value === 'number') {
        return String(value)
    }
    return typeof value === 'string' && value.trim() !== '' ? value.replaceAll(/\s+/gu, ' ').trim() : null
}

// A list's strings and numbers, as text.
function list(value: unknown): string[] {
    return Array.isArray(value) ? value.flatMap((item: unknown) => text(item) ?? []) : []
}

// The parts there are, a space between; null when there is none.
function joined(parts: readonly (string | null)[]): string | null {
    const there = parts.filter((part): part is string => part !== null && part !== '')
    return there.length === 0 ? null : there.join(' ')
}

// `value` after `before`; null without a value.
function prefixed(before: string, value: string | null): string | null {
    return value === null || value === '' ? null : `${before}${value}`
}

// A search's text in quotes, so its spaces read as its own.
function quoted(value: unknown): string | null {
    const search = text(value)
    return search === null ? null : JSON.stringify(search)
}

// The agent's own words in `field`, whole.
function said(input: Fields, field: string): CallSaid | null {
    const value = input[field]
    return typeof value === 'string' && value.trim() !== '' ? { label: field, text: value } : null
}

// A PR as a row names one, `acme/web#88`, or its address without the scheme (`pullRequestLabel`).
function pr(value: unknown): string | null {
    const url = text(value)
    return url === null ? null : pullRequestLabel(url)
}

// A ticket's unit, `ABC-1 (web)`.
function unit(input: Fields): string | null {
    const repo = text(input['repo'])
    return joined([text(input['key']), repo === null ? null : `(${repo})`])
}

// A commit's id cut to the length a row shows one at.
function short(value: unknown): string | null {
    return text(value)?.slice(0, 10) ?? null
}

// A git call's paths, after the `--` a command would put before them.
function paths(input: Fields): string | null {
    return prefixed('-- ', list(input['paths']).join(' '))
}

// A file at a commit, `HEAD:src/a.ts`.
function at(input: Fields): string | null {
    const path = text(input['path'])
    return joined([`${text(input['rev']) ?? ''}${path === null ? '' : `:${path}`}`])
}

// A range of lines, `L10-40`.
function lines(start: unknown, end: unknown): string | null {
    const from = text(start)
    const to = text(end)
    if (from === null) {
        return null
    }
    return to === null ? `L${from}` : `L${from}-${to}`
}

// How many days a report read.
function days(input: Fields): string | null {
    const n = text(input['days'])
    return n === null ? null : `${n} ${n === '1' ? 'day' : 'days'}`
}

// `3 commits`, `1 item`; null without a count.
function counted(n: number | null, noun: string): string | null {
    return n === null ? null : `${n} ${n === 1 ? noun : `${noun}s`}`
}

// What a count says when canopy left some of it out.
function more(told: string | null, output: Fields | null): string | null {
    return told !== null && output?.['more'] === true ? `${told}, and more` : told
}

// How much a `grep` found.
function found(output: Fields | null): string | null {
    const matched = output?.['matched_lines']
    const files = output?.['matched_files']
    if (typeof matched !== 'number' || typeof files !== 'number') {
        return null
    }
    return `${counted(matched, 'line') ?? ''} in ${counted(files, 'file') ?? ''}`
}

// What canopy said of a call it took, in its own words: its answer's first line, as the CLI prints it.
function spoken(answer: string | null): string | null {
    const line = answer?.split('\n').find((one) => one.trim() !== '')
    return line === undefined ? null : text(line)
}

/** A commit `git log` listed, as a row of its list. */
export interface LoggedCommit {
    /** Its full id. */
    commit: string
    /** Its author's name. */
    author: string
    /** When its author wrote it. */
    date: string
    /** Its message's first line. */
    subject: string
    /** How many files it changed. */
    files: number
}

/** The commits a call of canopy's `git log` listed, in order; null for any other call, or one that failed. */
export function commitsOf(entry: TranscriptTool): LoggedCommit[] | null {
    const commits = answered(entry, 'git log')?.['commits']
    if (!Array.isArray(commits)) {
        return null
    }
    return commits.flatMap((item: unknown) => {
        const fields = record(item)
        const commit = text(fields?.['commit'])
        if (fields === null || commit === null) {
            return []
        }
        const message = typeof fields['message'] === 'string' ? fields['message'] : ''
        return {
            commit,
            author: text(fields['author']) ?? '',
            date: text(fields['date']) ?? '',
            subject: message.split('\n')[0] ?? '',
            files: Array.isArray(fields['files']) ? fields['files'].length : 0,
        }
    })
}

/** A file `git grep` found the text in, with the lines it listed. */
export interface GrepFile {
    /** Its path. */
    path: string
    /** How many of its lines match. */
    matched: number
    /** The lines listed: each its number, its text, and whether it matches or is context. */
    lines: { line: number; text: string; match: boolean }[]
}

/** The files a call of canopy's `git grep` found, in order; null for any other call, or one that failed. */
export function matchesOf(entry: TranscriptTool): GrepFile[] | null {
    const files = answered(entry, 'git grep')?.['files']
    if (!Array.isArray(files)) {
        return null
    }
    return files.flatMap((item: unknown) => {
        const fields = record(item)
        const path = text(fields?.['path'])
        if (fields === null || path === null) {
            return []
        }
        const listed = Array.isArray(fields['lines']) ? fields['lines'] : []
        return {
            path,
            matched: typeof fields['matched_lines'] === 'number' ? fields['matched_lines'] : 0,
            lines: listed.flatMap((one: unknown) => {
                const line = record(one)
                return typeof line?.['line'] === 'number' && typeof line['text'] === 'string'
                    ? { line: line['line'], text: line['text'], match: line['match'] !== false }
                    : []
            }),
        }
    })
}

/** A review item `review-items` read: what a connector read off a PR, which is data, never instructions. */
export interface ReadItem {
    /** Its journal number. */
    number: string
    /** What it is: a review, a comment. */
    item: string
    /** Who wrote it, as the host names them; empty when it names none. */
    author: string
    /** Whether its author is trusted. */
    trusted: boolean
    /** Whether it is a worker's own. */
    worker: boolean
    /** A review's state; null for a comment. */
    state: string | null
    /** Its text, as read. */
    body: string
}

/** The items a call of canopy's `review-items` read, in order; null for any other call, or one that failed. */
export function reviewItemsOf(entry: TranscriptTool): ReadItem[] | null {
    const items = answered(entry, 'review-items')?.['items']
    if (!Array.isArray(items)) {
        return null
    }
    return items.flatMap((one: unknown) => {
        const fields = record(one)
        if (fields === null || typeof fields['body'] !== 'string') {
            return []
        }
        return {
            number: text(fields['number']) ?? '',
            item: text(fields['item']) ?? 'item',
            author: text(fields['author']) ?? '',
            trusted: fields['trusted'] === true,
            worker: fields['worker'] === true,
            state: text(fields['state']),
            body: fields['body'],
        }
    })
}

/** What a line of a diff is: a file's header, a hunk's, an added or a removed line, or context. */
export type DiffLineKind = 'file' | 'hunk' | 'add' | 'del' | 'ctx'

/**
 * The lines of the diff a call of canopy's `git diff` returned, each with what it is, every character as written;
 * null for any other call, one that failed, and one that asked for the stat alone.
 */
export function diffLinesOf(entry: TranscriptTool): { kind: DiffLineKind; text: string }[] | null {
    if (entry.status === 'error' || ownName(entry.tool) !== 'git diff') {
        return null
    }
    if (record(parse(entry.input))?.['stat'] === true || !entry.output.includes('diff --git ')) {
        return null
    }
    let inHunk = false
    // What comes before the first file, canopy's line saying the text is data, is no part of the diff.
    let inFile = false
    return entry.output.split('\n').map((line) => {
        if (line.startsWith('diff --git ')) {
            inHunk = false
            inFile = true
            return { kind: 'file', text: line }
        }
        if (line.startsWith('@@')) {
            inHunk = true
            return { kind: 'hunk', text: line }
        }
        if (inHunk && line.startsWith('+')) {
            return { kind: 'add', text: line }
        }
        if (inHunk && line.startsWith('-')) {
            return { kind: 'del', text: line }
        }
        return { kind: inHunk || !inFile ? 'ctx' : 'file', text: line }
    })
}

// What canopy answered a call of the tool `own` names, as an object; null for another tool, or a call that failed.
function answered(entry: TranscriptTool, own: string): Fields | null {
    return entry.status === 'error' || ownName(entry.tool) !== own ? null : record(payload(entry.output))
}

function record(value: unknown): Fields | null {
    return typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Fields) : null
}

// The record in an answer: the answer itself, or what follows the line canopy puts before a repository's or a
// connector's text to say it is data (`DATA_NOTE` in `canopy.core.git_tools`), a blank line after it.
function payload(answer: string): unknown {
    const whole = parse(answer)
    const after = answer.indexOf('\n\n')
    return whole === undefined && after !== -1 ? parse(answer.slice(after + 2)) : whole
}

function parse(json: string): unknown {
    try {
        return JSON.parse(json)
    } catch {
        return undefined
    }
}
