import { describe, expect, it } from 'vitest'

import { ROW_COLUMNS, rowLineFrom, rowTemplate } from './rows'

describe('rowTemplate', () => {
    it('names each column before its width, and the end after the last', () => {
        expect(rowTemplate('chore')).toBe('[name] 10rem [state] minmax(0,1fr) [findings] 8rem [end]')
    })

    it('gives every kind exactly one free column, so its fixed ones line up row to row', () => {
        for (const columns of Object.values(ROW_COLUMNS)) {
            expect(columns.filter(([, width]) => width === 'minmax(0,1fr)')).toHaveLength(1)
        }
    })

    it('names no column twice in a kind', () => {
        for (const columns of Object.values(ROW_COLUMNS)) {
            const names = columns.map(([name]) => name)
            expect(new Set(names).size).toBe(names.length)
        }
    })
})

describe('rowLineFrom', () => {
    it('spans from the named column to the end', () => {
        expect(rowLineFrom('title')).toBe('col-[title/end]')
    })
})
