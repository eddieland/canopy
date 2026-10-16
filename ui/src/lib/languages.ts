// The language a diff's file is written in, by its name, for the syntax highlighter (`src/lib/highlight.ts`). Each
// language's grammar is its own chunk, loaded the first time a diff shows a file in it, so a page with no diff, or a
// diff in languages no one opens, never downloads one.

import type { LanguageRegistration } from 'shiki/core'

import type { DiffFile } from '@/api/types'
import { DIFF_BUDGET, lineCount } from '@/lib/review-folds'

/** A grammar's loader: a Shiki language module, imported on demand. */
type Loader = () => Promise<{ default: LanguageRegistration[] }>

// The grammars a diff can be highlighted in, by Shiki's name for each. Written out so the bundler sees each import.
const LOADERS = {
    c: () => import('shiki/langs/c.mjs'),
    css: () => import('shiki/langs/css.mjs'),
    docker: () => import('shiki/langs/docker.mjs'),
    go: () => import('shiki/langs/go.mjs'),
    html: () => import('shiki/langs/html.mjs'),
    ini: () => import('shiki/langs/ini.mjs'),
    java: () => import('shiki/langs/java.mjs'),
    javascript: () => import('shiki/langs/javascript.mjs'),
    json: () => import('shiki/langs/json.mjs'),
    jsonc: () => import('shiki/langs/jsonc.mjs'),
    jsx: () => import('shiki/langs/jsx.mjs'),
    kotlin: () => import('shiki/langs/kotlin.mjs'),
    make: () => import('shiki/langs/make.mjs'),
    markdown: () => import('shiki/langs/markdown.mjs'),
    python: () => import('shiki/langs/python.mjs'),
    rust: () => import('shiki/langs/rust.mjs'),
    shellscript: () => import('shiki/langs/shellscript.mjs'),
    sql: () => import('shiki/langs/sql.mjs'),
    swift: () => import('shiki/langs/swift.mjs'),
    toml: () => import('shiki/langs/toml.mjs'),
    tsx: () => import('shiki/langs/tsx.mjs'),
    typescript: () => import('shiki/langs/typescript.mjs'),
    xml: () => import('shiki/langs/xml.mjs'),
    yaml: () => import('shiki/langs/yaml.mjs'),
} satisfies Record<string, Loader>

/** A language a diff can be highlighted in, by Shiki's name for it. */
export type Language = keyof typeof LOADERS

// A file's extension, lowercased, to its language.
const BY_EXTENSION: Record<string, Language> = {
    bash: 'shellscript',
    c: 'c',
    cfg: 'ini',
    cjs: 'javascript',
    css: 'css',
    cts: 'typescript',
    go: 'go',
    h: 'c',
    htm: 'html',
    html: 'html',
    ini: 'ini',
    java: 'java',
    js: 'javascript',
    json: 'json',
    jsonc: 'jsonc',
    jsx: 'jsx',
    kt: 'kotlin',
    kts: 'kotlin',
    md: 'markdown',
    mjs: 'javascript',
    mk: 'make',
    mts: 'typescript',
    py: 'python',
    pyi: 'python',
    rs: 'rust',
    sh: 'shellscript',
    sql: 'sql',
    svg: 'xml',
    swift: 'swift',
    toml: 'toml',
    ts: 'typescript',
    tsx: 'tsx',
    xml: 'xml',
    yaml: 'yaml',
    yml: 'yaml',
    zsh: 'shellscript',
}

// A file's whole name to its language, for the files named for what they are rather than by an extension.
const BY_NAME: Record<string, Language> = {
    '.bashrc': 'shellscript',
    '.editorconfig': 'ini',
    '.gitconfig': 'ini',
    '.zshrc': 'shellscript',
    Containerfile: 'docker',
    Dockerfile: 'docker',
    GNUmakefile: 'make',
    Makefile: 'make',
    'uv.lock': 'toml',
}

/** The language of the file at `path`, by its name and then its extension, or undefined when it is none of them. */
export function languageOf(path: string): Language | undefined {
    const name = path.slice(path.lastIndexOf('/') + 1)
    const byName = BY_NAME[name]
    if (byName !== undefined) {
        return byName
    }
    const dot = name.lastIndexOf('.')
    // A dotfile's name is not its extension: `.env` names no language.
    return dot > 0 ? BY_EXTENSION[name.slice(dot + 1).toLowerCase()] : undefined
}

/**
 * The language to highlight `file` in: its language, unless its hunks hold more lines than the page draws of a diff at
 * first (`DIFF_BUDGET`). A file that long is mostly folded away, and reading it costs the page seconds of work for
 * lines no one may open, so it stays plain, as a line too long for the grammar does; its grammar never loads.
 */
export function highlightLanguage(file: DiffFile): Language | undefined {
    return lineCount(file) > DIFF_BUDGET.page ? undefined : languageOf(file.path)
}

/** The loader of `language`'s grammar, which Shiki's `loadLanguage` takes as it is. */
export function loaderOf(language: Language): Loader {
    return LOADERS[language]
}
