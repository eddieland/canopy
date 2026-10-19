// Code as tokens a page can color by what each piece is: a keyword, a string, a constant, a function's or type's name,
// a comment, or anything else. Shiki tokenizes it with its language's TextMate grammar, as an editor would: a guide's
// code block whole, and a diff one side of a hunk at a time: the new side (its context and added lines) and, when it
// removes any, the old (its context and deleted lines), so a string or comment that spans lines is read whole. A hunk
// starts wherever git cut it, so a grammar starts there too: a hunk opened inside a long comment reads it as code. The
// tokens of a line joined are its text, or the line has none and stays plain. The result is data that a component
// renders as React text, never HTML. Only this module imports Shiki, and only on demand (`src/hooks/use-highlight.ts`).
//
// A side is read `CHUNK` lines at a time, each chunk starting in the grammar state the last one ended in, so it reads
// as if whole; and the page runs between chunks once the highlighter has worked for `SLICE_MS`. A diff at the server's
// bounds read at once held the page still for seconds, no click or scroll answered.

import { createCssVariablesTheme, createHighlighterCore } from 'shiki/core'
import type { GrammarState, HighlighterCore, ThemedToken } from 'shiki/core'
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript'

import type { DiffHunk } from '@/api/types'
import { loaderOf } from '@/lib/languages'
import type { Language } from '@/lib/languages'

/** What a piece of code is, as its color says: anything the grammar names otherwise is `text`. */
export type CodeKind = 'keyword' | 'string' | 'constant' | 'function' | 'comment' | 'text'

/** A piece of a line, as written. */
export interface CodeToken {
    /** What the piece is. */
    kind: CodeKind
    /** The piece's characters, as written. */
    text: string
}

// Shiki's theme of CSS variables, whose every color is `var(--syntax-NAME)`: it says which scopes are which kind, and
// the colors are only names, mapped to a kind below and to a token by the component. Nothing reads the variables.
const PREFIX = '--syntax-'
const THEME = createCssVariablesTheme({ name: 'canopy', variablePrefix: PREFIX, fontStyle: false })

const KINDS: Record<string, CodeKind> = {
    [`var(${PREFIX}token-keyword)`]: 'keyword',
    [`var(${PREFIX}token-string)`]: 'string',
    [`var(${PREFIX}token-string-expression)`]: 'string',
    [`var(${PREFIX}token-constant)`]: 'constant',
    [`var(${PREFIX}token-function)`]: 'function',
    [`var(${PREFIX}token-comment)`]: 'comment',
}

// A line this long or longer is left plain: the server cuts a diff's lines at 1000 characters, so such a line is cut
// mid-token, or minified, which would take the grammar a long time and show nothing useful.
const MAX_LINE = 1000
// How many lines the grammar reads in one go, and how long the highlighter works before the page may run.
const CHUNK = 200
const SLICE_MS = 12

/**
 * The tokens of each line of each of `hunks`, in `language`, by hunk and then line as the hunks hold them. A line
 * Shiki could not account for exactly is undefined, and stays plain.
 */
export async function highlightHunks(
    language: Language,
    hunks: readonly DiffHunk[],
): Promise<(CodeToken[] | undefined)[][]> {
    const shiki = await highlighter()
    await shiki.loadLanguage(loaderOf(language))
    const tokenize = async (hunk: DiffHunk, side: 'old' | 'new') => {
        const lines = hunk.lines.filter((line) => line.kind !== (side === 'new' ? 'del' : 'add'))
        const tokens = await tokenizeLines(
            shiki,
            language,
            lines.map((line) => line.text),
        )
        return new Map(lines.map((line, i) => [line, exactly(line.text, tokens[i])]))
    }
    const result: (CodeToken[] | undefined)[][] = []
    for (const hunk of hunks) {
        // oxlint-disable-next-line eslint/no-await-in-loop -- one hunk after another, so the page runs between them
        const sides = await tokenize(hunk, 'new')
        if (hunk.lines.some((line) => line.kind === 'del')) {
            // oxlint-disable-next-line eslint/no-await-in-loop -- as above
            for (const [line, tokens] of await tokenize(hunk, 'old')) {
                if (line.kind === 'del') {
                    sides.set(line, tokens)
                }
            }
        }
        result.push(hunk.lines.map((line) => sides.get(line)))
    }
    return result
}

/**
 * The tokens of each of `lines`, read whole in `language`, as a guide's code block holds them. A line Shiki could not
 * account for exactly is undefined, and stays plain.
 */
export async function highlightLines(
    language: Language,
    lines: readonly string[],
): Promise<(CodeToken[] | undefined)[]> {
    const shiki = await highlighter()
    await shiki.loadLanguage(loaderOf(language))
    const tokens = await tokenizeLines(shiki, language, lines)
    return lines.map((line, i) => exactly(line, tokens[i]))
}

/** What Shiki's color for a token says it is: `text` for a color the theme gives nothing in particular. */
export function kindOf(color: string | undefined): CodeKind {
    return (color === undefined ? undefined : KINDS[color]) ?? 'text'
}

// One highlighter for the page, made the first time code is highlighted. Each language loads into it once.
let shared: Promise<HighlighterCore> | undefined

function highlighter(): Promise<HighlighterCore> {
    shared ??= createHighlighterCore({
        themes: [THEME],
        langs: [],
        // Oniguruma's regexes compiled to JavaScript's, so no WebAssembly; a pattern JavaScript cannot express is
        // skipped rather than failing the grammar.
        engine: createJavaScriptRegexEngine({ forgiving: true }),
    })
    return shared
}

// Each of `texts` as tokens, read `CHUNK` lines at a time, each chunk from the state the last left the grammar in.
async function tokenizeLines(shiki: HighlighterCore, language: Language, texts: readonly string[]) {
    const tokens: ThemedToken[][] = []
    let state: GrammarState | undefined
    for (let at = 0; at < texts.length; at += CHUNK) {
        // oxlint-disable-next-line eslint/no-await-in-loop -- the page runs between chunks: that is the point
        await letThePageRun()
        const chunk = shiki.codeToTokensBase(texts.slice(at, at + CHUNK).join('\n'), {
            lang: language,
            theme: THEME.name,
            tokenizeMaxLineLength: MAX_LINE,
            grammarState: state,
        })
        state = shiki.getLastGrammarState(chunk)
        tokens.push(...chunk)
    }
    return tokens
}

// When the highlighter last let the page run. One for the page, since every file's highlighting shares its thread.
let ranAt = 0

// Lets the page run, a click or a frame, once the highlighter has worked `SLICE_MS` since it last did.
async function letThePageRun(): Promise<void> {
    if (performance.now() - ranAt >= SLICE_MS) {
        await new Promise((resolve) => {
            setTimeout(resolve, 0)
        })
        ranAt = performance.now()
    }
}

// A line's tokens, with neighbors of the same kind joined, or undefined when they do not spell `text` exactly.
function exactly(text: string, tokens: readonly ThemedToken[] | undefined): CodeToken[] | undefined {
    if (tokens === undefined) {
        return undefined
    }
    const joined: CodeToken[] = []
    for (const token of tokens) {
        const kind = kindOf(token.color)
        const last = joined.at(-1)
        if (last?.kind === kind) {
            last.text += token.content
        } else {
            joined.push({ kind, text: token.content })
        }
    }
    return joined.map((token) => token.text).join('') === text ? joined : undefined
}
