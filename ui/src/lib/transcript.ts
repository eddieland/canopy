import type {
    TranscriptEntry,
    TranscriptPrompt,
    TranscriptStep,
    TranscriptText,
    TranscriptTokens,
    TranscriptTool,
} from '@/api/types'
import { indent, tokenize } from '@/lib/json-lines'
import { literal } from '@/lib/search'

// A value longer than this is left out of a call's summary; a summary or outcome line is cut at `MAX_LINE`.
const MAX_VALUE = 80
const MAX_LINE = 200

/** How long after `start` an ISO time was, as a readout: `+0:42`, `+12:05`, `+1:02:09`. Empty without both times. */
export function elapsed(at: string | null, start: string | null): string {
    if (at === null || start === null) {
        return ''
    }
    const seconds = Math.max(0, Math.floor((Date.parse(at) - Date.parse(start)) / 1000))
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = String(seconds % 60).padStart(2, '0')
    return h > 0 ? `+${h}:${String(m).padStart(2, '0')}:${s}` : `+${m}:${s}`
}

/** A duration in milliseconds as a readout: `840ms`, `14s`, `3m 05s`. */
export function duration(ms: number): string {
    if (ms < 1000) {
        return `${ms}ms`
    }
    const seconds = Math.round(ms / 1000)
    if (seconds < 60) {
        return `${seconds}s`
    }
    return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`
}

/** A token count as the CLI says it (`agent_output.Usage.describe`): `950`, `12.3k`, `1.2M`. */
export function tokenCount(n: number): string {
    if (n >= 1_000_000) {
        return `${(n / 1_000_000).toFixed(1)}M`
    }
    if (n >= 1_000) {
        return `${(n / 1_000).toFixed(1)}k`
    }
    return String(n)
}

/**
 * A run's tokens after its cost, as the CLI says them (`agent_output.Usage.describe`): `, 12.3k tokens, 45.6k peak
 * context`, the peak only when it was recorded, and nothing when the runtime reported no tokens.
 */
export function runTokens(newTokens: number | null, peakContext: number | null): string {
    if (newTokens === null) {
        return ''
    }
    const peak = peakContext === null ? '' : `, ${tokenCount(peakContext)} peak context`
    return `, ${tokenCount(newTokens)} tokens${peak}`
}

/** A change in tokens with its sign, as the context chart and By call say a step: `+4.3k`, `-2.0k`, `+0`. */
export function signed(n: number): string {
    return n < 0 ? `-${tokenCount(-n)}` : `+${tokenCount(n)}`
}

/** A token count in a list's column, with what it counts (`12.3k tokens`), or a dash when nothing reported one. */
export function tokensCell(n: number | null, counts: string): string {
    return n === null ? '–' : `${tokenCount(n)} ${counts}`
}

/** What a run's or a tick's token counts mean, for the hover on them. */
export const RUN_TOKENS_TITLE =
    'tokens: input, cache writes, output, and reasoning, summed over its model calls; cache reads are left out, ' +
    'since each call reads again what the calls before it were sent. peak context: the most one call was sent.'

/** What a transcript holds, counted. */
export interface Tally {
    /** Tool calls. */
    tools: number
    /** Tool calls that ended in an error, a canopy command's refusals not included. */
    failed: number
    /** canopy commands the harness refused. */
    refused: number
    /** Model calls. */
    calls: number
    /** Errors the runtime reported. */
    errors: number
}

/** How many tool calls, failed and refused ones, model calls, and runtime errors a transcript holds. */
export function tally(entries: TranscriptEntry[]): Tally {
    const found: Tally = { tools: 0, failed: 0, refused: 0, calls: 0, errors: 0 }
    for (const entry of entries) {
        if (entry.kind === 'tool') {
            found.tools += 1
            const { verdict } = outcome(entry)
            if (verdict === 'failed') {
                found.failed += 1
            }
            if (verdict === 'refused') {
                found.refused += 1
            }
        } else if (entry.kind === 'step') {
            found.calls += 1
        } else if (entry.kind === 'error') {
            found.errors += 1
        }
    }
    return found
}

/** One model call, as the transcript shows it by call: what it was sent that no call before it was, and what it did. */
export interface ModelCall {
    /** Its number, from 1, in the order the runtime started its calls. */
    n: number
    /** What its tools returned to the call before it, which it was sent: a later call's input past its first. */
    returned: TranscriptTool[]
    /** What it did, in the order printed: its text and reasoning, its tool calls, and the runtime's errors. */
    output: TranscriptEntry[]
    /** How it ended, with its tokens and cost; null when the session ended first, or a bound cut it. */
    end: TranscriptStep | null
}

/** A transcript by model call: the calls in order, and the entries printed before the runtime started any. */
export interface ByCall {
    /** Entries the runtime printed before its first call, such as an error starting it. */
    before: TranscriptEntry[]
    /** The calls, in order. */
    calls: ModelCall[]
}

/**
 * A transcript's entries by the model call each came from. A call was sent everything before it; what is new in its
 * input is what the call before it asked its tools for, so each call after the first carries that call's tool calls,
 * which hold what they returned.
 */
export function byCall(entries: TranscriptEntry[]): ByCall {
    const before: TranscriptEntry[] = []
    const calls: ModelCall[] = []
    for (const entry of entries) {
        if (entry.call === null) {
            before.push(entry)
            continue
        }
        let call = calls.at(-1)
        if (call?.n !== entry.call) {
            const returned = (call?.output ?? []).filter((e): e is TranscriptTool => e.kind === 'tool')
            call = { n: entry.call, returned, output: [], end: null }
            calls.push(call)
        }
        if (entry.kind === 'step') {
            call.end = entry
        } else {
            call.output.push(entry)
        }
    }
    return { before, calls }
}

/** How many tokens a model call was sent, from the cache or not. */
export function sentTokens(tokens: TranscriptTokens): number {
    return tokens.input + tokens.cache_read + tokens.cache_write
}

/** How many tokens a model call wrote, its reasoning included. */
export function wroteTokens(tokens: TranscriptTokens): number {
    return tokens.output + tokens.reasoning
}

// How many characters make a token, roughly: for canopy's prompt, the one text sent whose tokens nobody counted apart.
const CHARS_PER_TOKEN = 4

/** One entry a model call's context grew by: what the call before it printed, which it was sent anew. */
export interface Addition {
    /** Its place in the transcript's entries, which the page shows it by. */
    i: number
    /** The entry: a tool call, its input and what it returned, or the agent's text. */
    entry: TranscriptText | TranscriptTool
    /** How many characters it holds. */
    chars: number
    /** Its share of the step up, in tokens, by its characters: an estimate, since the runtime counts only the whole. */
    tokens: number
}

/** One model call's context, as the transcript's chart draws it. */
export interface CallContext {
    /** Its number, from 1. */
    n: number
    /** What it was sent, from the cache or not; null when the runtime counted none. */
    sent: number | null
    /** Of `sent`, what was there before it: the call before's context, or, for the first, the runtime's own. */
    carried: number
    /** Of `sent`, what is new: for the first, canopy's prompt, estimated; else the step up from the call before. */
    added: number
    /** How many more tokens it was sent than the call before, below 0 if some were dropped; null without both. */
    step: number | null
    /** What the call before printed, largest first, sharing a step up: empty for the first, or with no step up. */
    additions: Addition[]
}

/** A transcript's context over its model calls. */
export interface ContextShape {
    /** Each model call, in order. */
    calls: CallContext[]
    /** The call sent the most, the first of them on a tie; null when the runtime counted none. */
    peak: CallContext | null
    /** canopy's prompt, in tokens, estimated from its characters; null when it kept none. */
    prompt: number | null
    /** The largest single addition, with the call it grew; null when no call grew. */
    largest: { call: CallContext; addition: Addition } | null
}

/**
 * How a session's context grew, call by call. A call is sent all that the call before was, then what that call
 * printed: its text and its tool calls, each with what it returned. So a step up between two calls is shared among
 * those entries by their characters, largest first, and the first call's context is canopy's prompt and the rest, the
 * runtime's own overhead: the agent's definition, its system prompt, and its tools.
 */
export function contextShape(entries: TranscriptEntry[], prompt: TranscriptPrompt | null): ContextShape {
    const printed: { n: number; sent: number | null; entries: Omit<Addition, 'tokens'>[] }[] = []
    for (const [i, entry] of entries.entries()) {
        if (entry.call === null) {
            continue
        }
        let call = printed.at(-1)
        if (call?.n !== entry.call) {
            call = { n: entry.call, sent: null, entries: [] }
            printed.push(call)
        }
        if (entry.kind === 'step') {
            call.sent = entry.split === null ? null : sentTokens(entry.split)
        } else if (entry.kind === 'text') {
            call.entries.push({ i, entry, chars: entry.text.length })
        } else if (entry.kind === 'tool') {
            call.entries.push({ i, entry, chars: entry.input.length + entry.output.length })
        }
    }
    const promptTokens = prompt === null ? null : Math.round(prompt.text.length / CHARS_PER_TOKEN)
    const calls = printed.map((call, k): CallContext => {
        const before = printed[k - 1]
        const sent = call.sent
        if (before === undefined) {
            const added = Math.min(sent ?? 0, promptTokens ?? 0)
            return { n: call.n, sent, carried: (sent ?? 0) - added, added, step: null, additions: [] }
        }
        if (sent === null || before.sent === null) {
            return { n: call.n, sent, carried: sent ?? 0, added: 0, step: null, additions: [] }
        }
        const step = sent - before.sent
        const added = Math.max(0, step)
        return { n: call.n, sent, carried: sent - added, added, step, additions: shared(before.entries, added) }
    })
    let peak: CallContext | null = null
    let largest: ContextShape['largest'] = null
    for (const call of calls) {
        if (call.sent !== null && call.sent > (peak?.sent ?? -1)) {
            peak = call
        }
        const top = call.additions[0]
        if (top !== undefined && top.tokens > (largest?.addition.tokens ?? 0)) {
            largest = { call, addition: top }
        }
    }
    return { calls, peak, prompt: promptTokens, largest }
}

/** A step up shared among the entries that made it, by their characters, largest first. */
function shared(entries: Omit<Addition, 'tokens'>[], step: number): Addition[] {
    const chars = entries.reduce((sum, e) => sum + e.chars, 0)
    if (step === 0 || chars === 0) {
        return []
    }
    return entries
        .map((e) => ({ ...e, tokens: Math.round((step * e.chars) / chars) }))
        .toSorted((a, b) => (b.chars === a.chars ? a.i - b.i : b.chars - a.chars))
}

/**
 * What a model call did, on one line: its first text's start, then its tool calls by name, a name it called more
 * than once counted (`read ×2`), then its errors.
 */
export function callLine(call: ModelCall): string {
    const text = call.output.find((e) => e.kind === 'text' && !e.reasoning)
    const tools = new Map<string, number>()
    let errors = 0
    for (const entry of call.output) {
        if (entry.kind === 'tool') {
            tools.set(entry.tool, (tools.get(entry.tool) ?? 0) + 1)
        } else if (entry.kind === 'error') {
            errors += 1
        }
    }
    const parts = [
        text?.kind === 'text' ? oneLine(text.text) : '',
        [...tools].map(([name, n]) => (n > 1 ? `${name} ×${n}` : name)).join(', '),
        errors > 0 ? `${errors} runtime ${errors === 1 ? 'error' : 'errors'}` : '',
    ]
    return parts
        .filter((p) => p !== '')
        .join(' · ')
        .slice(0, MAX_LINE)
}

/** The first time a transcript names, which every entry's `elapsed` counts from. */
export function startOf(entries: TranscriptEntry[]): string | null {
    return entries.find((e) => e.at !== null)?.at ?? null
}

/**
 * What a tool call did, on one line: a shell call's command, since its title is only what the agent said it was
 * for; else the runtime's title; else its input's short values as `key=value`, as `{"repo": "web", "pullNumber": 88}`
 * reads `repo=web pullNumber=88`. Empty when the input has none, or was cut and no longer parses.
 */
export function summary(entry: TranscriptTool): string {
    const input = parsed(entry.input)
    const command = input?.['command']
    if (typeof command === 'string') {
        return oneLine(command)
    }
    if (entry.title !== null) {
        return entry.title
    }
    if (input === null) {
        return ''
    }
    const pairs = Object.entries(input).flatMap(([key, value]) => {
        if (typeof value === 'number' || typeof value === 'boolean') {
            return [`${key}=${value}`]
        }
        if (typeof value !== 'string') {
            return []
        }
        const shown = oneLine(value)
        if (shown === '' || shown.length > MAX_VALUE) {
            return []
        }
        return [`${key}=${/\s/u.test(shown) ? JSON.stringify(shown) : shown}`]
    })
    return pairs.join(' ').slice(0, MAX_LINE)
}

/** How a tool call ended: `refused` and `failed` say why, from the harness's own words when it was a canopy command. */
export type Verdict = 'done' | 'failed' | 'refused'

/** What a tool call's row says of how it ended. */
export interface Outcome {
    /** How it ended. */
    verdict: Verdict
    /** The guard that refused it, as the journal names it (`capacity`), when `refused`. */
    guard: string | null
    /** What it printed, when that fits on its row: its error's first line, or an output of one short line. */
    line: string | null
}

/**
 * How a tool call ended, and what it printed when that fits on a line. A canopy command that exits 1 prints
 * `Error: <verb> refused (<guard>): <reason>` or `Error: <message>`, which the runtime still reports as a completed
 * call, so its output decides: a refusal is `refused`, any other error `failed`. Output of several lines, or of one
 * long one, has no line: the row opens to it.
 */
export function outcome(entry: TranscriptTool): Outcome {
    if (entry.status === 'error') {
        return { verdict: 'failed', guard: null, line: firstLine(entry.output) }
    }
    const input = parsed(entry.input)
    const command = input?.['command']
    if (typeof command === 'string' && /^\s*canopy\s/u.test(command)) {
        const error = /^Error: (.+)$/mu.exec(entry.output)?.[1]
        if (error !== undefined) {
            const guard = /\brefused \(([^)]+)\)/u.exec(error)?.[1] ?? null
            return { verdict: guard === null ? 'failed' : 'refused', guard, line: oneLine(error).slice(0, MAX_LINE) }
        }
    }
    const lines = entry.output.split('\n').filter((l) => l.trim() !== '')
    const only = lines.length === 1 ? oneLine(lines[0] ?? '') : ''
    const fits = only !== '' && only.length <= MAX_LINE && !/^[[{]/u.test(only)
    return { verdict: 'done', guard: null, line: fits ? only : null }
}

/**
 * A tool's output as it is shown opened: a JSON object or array indented, anything else as it was printed. Laid out
 * from its tokens, never parsed and printed again, so every value stays as written: a number past a double's
 * precision, an id in an API's response, is not rounded.
 */
export function pretty(output: string): string {
    return indent(tokenize(output))
        .map((token) => token.text)
        .join('')
}

/** A tool call's output as its opened row shows it: `pretty`, or `no output`. */
export function shownOutput(entry: TranscriptTool): string {
    return entry.output ? pretty(entry.output) : 'no output'
}

/** A transcript's search as typed, its ends trimmed, or null when that leaves nothing to find. */
export function findQueryOf(raw: string): string | null {
    const query = raw.trim()
    return query === '' ? null : query
}

/** How many lines of an entry hold a search's query. */
export interface Hits {
    /** Lines of its row: the agent's text, a tool call's name and line, an error. */
    row: number
    /** Lines of what it opens to: a tool call's input and output, as shown. */
    body: number
}

/**
 * How many of an entry's lines hold `query`, letters in either case, its characters taken literally. Lines are read
 * as the page shows them, so a match never spans a line break, and each line counts once however often it matches. A
 * model call is numbers alone, and never matches.
 */
export function hitsIn(entry: TranscriptEntry, query: string): Hits {
    switch (entry.kind) {
        case 'text': {
            return { row: linesHolding([entry.text], query), body: 0 }
        }
        case 'tool': {
            const row = [entry.tool, summary(entry), outcome(entry).line ?? '']
            return { row: linesHolding(row, query), body: linesHolding([entry.input, shownOutput(entry)], query) }
        }
        case 'step': {
            return { row: 0, body: 0 }
        }
        case 'error': {
            return { row: linesHolding([entry.name, entry.message], query), body: 0 }
        }
    }
}

function linesHolding(texts: string[], query: string): number {
    const pattern = new RegExp(literal(query), 'iu')
    return texts.flatMap((text) => text.split('\n')).filter((line) => pattern.test(line)).length
}

function oneLine(text: string): string {
    return text.replaceAll(/\s+/gu, ' ').trim()
}

function firstLine(text: string): string | null {
    const line = text.split('\n').find((l) => l.trim() !== '')
    return line === undefined ? null : oneLine(line).slice(0, MAX_LINE)
}

/** A tool's input as an object, or null when it is not one, or was cut and no longer parses. */
function parsed(input: string): Record<string, unknown> | null {
    const value = parsedJson(input)
    return typeof value === 'object' && value !== null && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : null
}

function parsedJson(text: string): unknown {
    try {
        return JSON.parse(text)
    } catch {
        return undefined
    }
}
