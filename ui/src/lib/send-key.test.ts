import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { DEFAULT, isApple, parseSendKey, sends, sendShortcut } from './send-key'
import type { KeyPress } from './send-key'

const ENTER: KeyPress = { key: 'Enter', shiftKey: false, ctrlKey: false, metaKey: false, isComposing: false }

// The setting is read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./send-key')
}

describe('parseSendKey', () => {
    it('defaults to Enter when nothing is stored', () => {
        expect(parseSendKey(null)).toBe(DEFAULT)
        expect(DEFAULT).toBe('enter')
    })

    it('reads what was stored, and falls back on anything else', () => {
        expect(parseSendKey('mod-enter')).toBe('mod-enter')
        expect(parseSendKey('button')).toBe('button')
        expect(parseSendKey('ctrl')).toBe(DEFAULT)
    })
})

describe('sends', () => {
    it('sends on Enter, and on Ctrl or ⌘ with it, under enter', () => {
        expect(sends('enter', ENTER)).toBe(true)
        expect(sends('enter', { ...ENTER, ctrlKey: true })).toBe(true)
        expect(sends('enter', { ...ENTER, metaKey: true })).toBe(true)
    })

    it('sends only on Ctrl+Enter or ⌘+Enter under mod-enter', () => {
        expect(sends('mod-enter', ENTER)).toBe(false)
        expect(sends('mod-enter', { ...ENTER, ctrlKey: true })).toBe(true)
        expect(sends('mod-enter', { ...ENTER, metaKey: true })).toBe(true)
    })

    it('never sends from the keyboard under button', () => {
        expect(sends('button', ENTER)).toBe(false)
        expect(sends('button', { ...ENTER, ctrlKey: true })).toBe(false)
    })

    it('never sends on Shift+Enter, an Enter ending a composition, or another key', () => {
        for (const setting of ['enter', 'mod-enter', 'button'] as const) {
            expect(sends(setting, { ...ENTER, shiftKey: true, ctrlKey: true })).toBe(false)
            expect(sends(setting, { ...ENTER, isComposing: true, ctrlKey: true })).toBe(false)
            expect(sends(setting, { ...ENTER, key: 'a', ctrlKey: true })).toBe(false)
        }
    })
})

describe('sendShortcut', () => {
    it('names Enter, the keyboard modifier with it, or nothing for the button', () => {
        expect(sendShortcut('enter', false)).toBe('Enter')
        expect(sendShortcut('mod-enter', false)).toBe('Control+Enter')
        expect(sendShortcut('mod-enter', true)).toBe('Meta+Enter')
        expect(sendShortcut('button', true)).toBeUndefined()
    })

    it('takes an Apple keyboard from the user agent', () => {
        expect(isApple('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')).toBe(true)
        expect(isApple('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)')).toBe(true)
        expect(isApple('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36')).toBe(false)
        expect(isApple('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe(false)
    })
})

describe('useSendKey', () => {
    beforeEach(() => localStorage.clear())

    it('changes the key that sends, and keeps it', async () => {
        const sendKey = await load()
        const { result } = renderHook(() => sendKey.useSendKey())
        expect(result.current).toBe('enter')

        act(() => sendKey.setSendKey('mod-enter'))
        expect(result.current).toBe('mod-enter')
        expect(localStorage.getItem(sendKey.STORAGE_KEY)).toBe('mod-enter')
    })

    it("follows another tab's setting, one made before it was read, and storage cleared", async () => {
        const sendKey = await load()
        localStorage.setItem(sendKey.STORAGE_KEY, 'button')
        const { result } = renderHook(() => sendKey.useSendKey())
        expect(result.current).toBe('button')

        act(() => otherTab(sendKey.STORAGE_KEY, 'mod-enter'))
        expect(result.current).toBe('mod-enter')
        act(() => otherTabClears())
        expect(result.current).toBe('enter')
    })

    it('sends on Enter where storage is unavailable, and still changes for this page', async () => {
        breakStorage()
        const sendKey = await load()
        const { result } = renderHook(() => sendKey.useSendKey())
        expect(result.current).toBe('enter')

        act(() => sendKey.setSendKey('button'))
        expect(result.current).toBe('button')
    })
})
