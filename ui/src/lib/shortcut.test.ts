import { describe, expect, it } from 'vitest'

import { ariaKeys, isPressed, keysLabel } from '@/lib/shortcut'

describe('keysLabel', () => {
    it('names a shortcut with symbols on an Apple keyboard and with words elsewhere', () => {
        expect(keysLabel('Mod-Alt-m', true)).toBe('⌘⌥M')
        expect(keysLabel('Mod-Alt-m', false)).toBe('Ctrl+Alt+M')
        expect(keysLabel('Mod-Shift-8', true)).toBe('⌘⇧8')
        expect(keysLabel('Mod-Shift-8', false)).toBe('Ctrl+Shift+8')
    })
})

describe('ariaKeys', () => {
    it('names a shortcut as aria-keyshortcuts does', () => {
        expect(ariaKeys('Mod-b', true)).toBe('Meta+B')
        expect(ariaKeys('Mod-Alt-1', false)).toBe('Control+Alt+1')
    })
})

describe('isPressed', () => {
    const press = { key: 's', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false }

    it('takes Mod as ⌘ on an Apple keyboard and Ctrl elsewhere', () => {
        expect(isPressed('Mod-s', { ...press, metaKey: true }, true)).toBe(true)
        expect(isPressed('Mod-s', { ...press, ctrlKey: true }, false)).toBe(true)
        expect(isPressed('Mod-s', { ...press, ctrlKey: true }, true)).toBe(false)
        expect(isPressed('Mod-s', { ...press, metaKey: true }, false)).toBe(false)
    })

    it("needs the shortcut's modifiers and no others, whatever the case of its key", () => {
        expect(isPressed('Mod-s', { ...press, key: 'S', ctrlKey: true }, false)).toBe(true)
        expect(isPressed('Mod-s', { ...press, ctrlKey: true, shiftKey: true }, false)).toBe(false)
        expect(isPressed('Mod-Alt-m', { ...press, key: 'm', ctrlKey: true, altKey: true }, false)).toBe(true)
        expect(isPressed('Mod-s', press, false)).toBe(false)
    })
})
