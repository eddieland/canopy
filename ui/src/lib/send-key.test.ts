import { describe, expect, it } from 'vitest'

import { DEFAULT, isApple, parseSendKey, sends, sendShortcut } from './send-key'
import type { KeyPress } from './send-key'

const ENTER: KeyPress = { key: 'Enter', shiftKey: false, ctrlKey: false, metaKey: false, isComposing: false }

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
