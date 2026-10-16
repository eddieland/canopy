import { describe, expect, it } from 'vitest'

import { ariaKeys, keysLabel } from '@/lib/shortcut'

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
