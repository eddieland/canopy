import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { mockAttention } from '@/api/mocks'
import type { AttentionItem } from '@/api/types'
import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { parseHidden, withoutFindings } from './attention-findings'

// The setting is read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./attention-findings')
}

describe('parseHidden', () => {
    it('shows findings until they are hidden, and for anything it does not recognize', () => {
        expect(parseHidden(null)).toBe(false)
        expect(parseHidden('show')).toBe(false)
        expect(parseHidden('yes')).toBe(false)
        expect(parseHidden('hide')).toBe(true)
    })
})

describe('withoutFindings', () => {
    it("leaves out chores' findings alone, a chore that failed kept, in the list's order", () => {
        const item = mockAttention[0] as AttentionItem
        const failed = { ...item, id: 'c1', reason: 'chore_failed', chore: 'deps', ticket_key: null }
        const finding = { ...failed, id: 'c2', reason: 'lodash-advisory', finding: true }
        expect(withoutFindings([finding, item, failed]).map((i) => i.id)).toEqual([item.id, 'c1'])
    })
})

describe('useFindingsHidden', () => {
    beforeEach(() => localStorage.clear())

    it('hides findings, keeps it, and shows them again', async () => {
        const findings = await load()
        const { result } = renderHook(() => findings.useFindingsHidden())
        expect(result.current).toBe(false)

        act(() => findings.setFindingsHidden(true))
        expect(result.current).toBe(true)
        expect(localStorage.getItem(findings.STORAGE_KEY)).toBe('hide')
        act(() => findings.setFindingsHidden(false))
        expect(result.current).toBe(false)
    })

    it("follows another tab's setting, one made before it was read, and storage cleared", async () => {
        const findings = await load()
        localStorage.setItem(findings.STORAGE_KEY, 'hide')
        const { result } = renderHook(() => findings.useFindingsHidden())
        expect(result.current).toBe(true)

        act(() => otherTab(findings.STORAGE_KEY, 'show'))
        expect(result.current).toBe(false)
        act(() => otherTab(findings.STORAGE_KEY, 'hide'))
        expect(result.current).toBe(true)
        act(() => otherTabClears())
        expect(result.current).toBe(false)
    })

    it('shows findings where storage is unavailable, and still hides them for this page', async () => {
        breakStorage()
        const findings = await load()
        const { result } = renderHook(() => findings.useFindingsHidden())
        expect(result.current).toBe(false)

        act(() => findings.setFindingsHidden(true))
        expect(result.current).toBe(true)
    })
})
