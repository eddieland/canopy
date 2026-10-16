import { describe, expect, it } from 'vitest'

import { languageOf } from '@/lib/languages'

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
