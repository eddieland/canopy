import { describe, expect, it } from 'vitest'

import type { DiffFile } from '@/api/types'
import { highlightLanguage, languageOf } from '@/lib/languages'
import { DIFF_BUDGET } from '@/lib/review-folds'

describe('languageOf', () => {
    it('reads a language from a file extension, whatever its case', () => {
        expect(languageOf('src/canopy/core/db.py')).toBe('python')
        expect(languageOf('ui/src/lib/highlight.ts')).toBe('typescript')
        expect(languageOf('ui/src/components/review-diff.tsx')).toBe('tsx')
        expect(languageOf('docs/README.MD')).toBe('markdown')
        expect(languageOf('migrations/0001_init.sql')).toBe('sql')
    })

    it('reads a language from a whole file name before its extension', () => {
        expect(languageOf('Makefile')).toBe('make')
        expect(languageOf('docker/Dockerfile')).toBe('docker')
        expect(languageOf('uv.lock')).toBe('toml')
        expect(languageOf('.editorconfig')).toBe('ini')
    })

    it('names no language for a file it does not know', () => {
        expect(languageOf('LICENSE')).toBeUndefined()
        expect(languageOf('tests/fakes/agent')).toBeUndefined()
        expect(languageOf('logo.png')).toBeUndefined()
        // A dotfile's name is not an extension, and a directory's dot is not the file's.
        expect(languageOf('.env')).toBeUndefined()
        expect(languageOf('.github/CODEOWNERS')).toBeUndefined()
    })
})

// A file of `count` added lines, in hunks of 100 at most.
const file = (path: string, count: number): DiffFile => ({
    path,
    old_path: null,
    binary: false,
    hunks: Array.from({ length: Math.ceil(count / 100) }, (_, h) => ({
        header: '',
        lines: Array.from({ length: Math.min(100, count - h * 100) }, () => ({
            kind: 'add' as const,
            old: null,
            new: null,
            text: '',
        })),
    })),
})

describe('highlightLanguage', () => {
    it('highlights a file in its language up to as many lines as the page draws at first, across its hunks', () => {
        expect(highlightLanguage(file('src/a.py', DIFF_BUDGET.page))).toBe('python')
        expect(highlightLanguage(file('src/a.py', DIFF_BUDGET.page + 1))).toBeUndefined()
    })

    it('highlights no file in no language, however short', () => {
        expect(highlightLanguage(file('notes.txt', 3))).toBeUndefined()
    })
})
