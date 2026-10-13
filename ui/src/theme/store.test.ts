import { beforeEach, describe, expect, it, vi } from 'vitest'

import { stubSystemTheme } from '@/test-utils'

// The store reads storage and the system theme when it loads, so each test imports a fresh copy.
function load() {
    vi.resetModules()
    return import('./store')
}

beforeEach(() => {
    localStorage.clear()
    document.documentElement.className = ''
})

describe('theme store', () => {
    it('follows the system theme when nothing is stored', async () => {
        stubSystemTheme(true)
        const store = await load()
        expect(store.getSnapshot()).toEqual({ preference: 'system', resolved: 'dark' })
    })

    it('stores, applies, and announces a preference', async () => {
        stubSystemTheme(false)
        const store = await load()
        const listener = vi.fn<() => void>()
        const unsubscribe = store.subscribe(listener)

        store.setPreference('dark')

        expect(localStorage.getItem(store.STORAGE_KEY)).toBe('dark')
        expect(document.documentElement.classList.contains('dark')).toBe(true)
        expect(document.documentElement.style.colorScheme).toBe('dark')
        expect(listener).toHaveBeenCalledTimes(1)

        store.setPreference('system')
        expect(localStorage.getItem(store.STORAGE_KEY)).toBeNull()
        expect(document.documentElement.classList.contains('dark')).toBe(false)
        unsubscribe()
    })

    it('picks up a change made in another tab', async () => {
        stubSystemTheme(false)
        const store = await load()
        const listener = vi.fn<() => void>()
        store.subscribe(listener)

        localStorage.setItem(store.STORAGE_KEY, 'dark')
        globalThis.dispatchEvent(new StorageEvent('storage', { key: store.STORAGE_KEY, newValue: 'dark' }))

        expect(store.getSnapshot().resolved).toBe('dark')
        expect(document.documentElement.classList.contains('dark')).toBe(true)
        expect(listener).toHaveBeenCalled()
    })

    it('catches a system change made before anything subscribed', async () => {
        const system = stubSystemTheme(true)
        const store = await load()
        document.documentElement.classList.add('dark')

        system.set(false)
        const listener = vi.fn<() => void>()
        store.subscribe(listener)

        expect(store.getSnapshot().resolved).toBe('light')
        expect(document.documentElement.classList.contains('dark')).toBe(false)
        expect(listener).toHaveBeenCalled()
    })

    it('follows a system change only while the preference is system', async () => {
        const system = stubSystemTheme(false)
        const store = await load()
        store.subscribe(() => {})

        system.set(true)
        expect(store.getSnapshot().resolved).toBe('dark')

        store.setPreference('light')
        system.set(false)
        system.set(true)
        expect(store.getSnapshot().resolved).toBe('light')
    })
})
