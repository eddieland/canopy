import { describe, expect, it } from 'vitest'

import { DEFAULT, type KeyPress, parseSendKey, sends } from './send-key'

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
