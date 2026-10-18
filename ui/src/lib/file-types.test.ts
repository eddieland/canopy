import { describe, expect, it } from 'vitest'

import { fileType, fileTypes, fileTypesLabel, hiddenFilesText, NO_EXTENSION } from './file-types'

describe('fileType', () => {
    it("is a file name's last extension, lowercased", () => {
        expect(fileType('src/a.ts')).toBe('.ts')
        expect(fileType('src/types.d.ts')).toBe('.ts')
        expect(fileType('docs/README.MD')).toBe('.md')
        expect(fileType('a.b/c.tsx')).toBe('.tsx')
    })

    it('is no extension for a name with no dot but at its start, or one at its end', () => {
        expect(fileType('Makefile')).toBe(NO_EXTENSION)
        expect(fileType('.gitignore')).toBe(NO_EXTENSION)
        expect(fileType('src.d/Dockerfile')).toBe(NO_EXTENSION)
        expect(fileType('notes.')).toBe(NO_EXTENSION)
    })
})

describe('fileTypes', () => {
    it('counts the files of each type, in order by name, those with no extension last', () => {
        expect(fileTypes(['b.ts', 'Makefile', 'a.py', 'c.ts', '.env'])).toStrictEqual([
            { type: '.py', count: 1 },
            { type: '.ts', count: 2 },
            { type: NO_EXTENSION, count: 2 },
        ])
        expect(fileTypes([])).toStrictEqual([])
    })
})

describe('fileTypesLabel', () => {
    const types = fileTypes(['a.ts', 'b.py', 'c.md'])

    it('says how many types show', () => {
        expect(fileTypesLabel(types, new Set())).toBe('All file types')
        expect(fileTypesLabel(types, new Set(['.md']))).toBe('2 of 3 file types')
        expect(fileTypesLabel(types, new Set(['.md', '.py']))).toBe('.ts only')
        expect(fileTypesLabel(types, new Set(['.md', '.py', '.ts']))).toBe('No file types')
    })
})

describe('hiddenFilesText', () => {
    it('counts the files hidden', () => {
        expect(hiddenFilesText(1)).toBe('1 file hidden by type')
        expect(hiddenFilesText(12)).toBe('12 files hidden by type')
    })
})
