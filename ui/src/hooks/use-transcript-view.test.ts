import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { useTranscriptView } from './use-transcript-view'

afterEach(cleanup)

describe('useTranscriptView', () => {
    it('takes the search as typed, and draws the rows for it once React gets to it', () => {
        const { result } = renderHook(() => useTranscriptView())
        act(() => result.current.setTyped('kingfisher'))
        expect(result.current.typed).toBe('kingfisher')
        expect(result.current.found).toBe('kingfisher')
    })

    it('shows a row in order and unsearched, again on each showing', () => {
        const { result } = renderHook(() => useTranscriptView())
        act(() => {
            result.current.setGrouped(true)
            result.current.setTyped('kingfisher')
        })
        act(() => result.current.show(12))
        expect(result.current).toMatchObject({ grouped: false, typed: '', found: '', target: { i: 12, round: 1 } })
        act(() => result.current.show(12))
        expect(result.current.target).toEqual({ i: 12, round: 2 })
    })
})
