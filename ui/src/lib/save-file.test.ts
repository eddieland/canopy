import { afterEach, describe, expect, it, vi } from 'vitest'

import { fileWords, saveFile } from './save-file'

afterEach(() => {
    vi.useRealTimers()
})

describe('saveFile', () => {
    it('downloads the blob under its name, from a link it leaves nowhere, and lets the blob go after a while', () => {
        vi.useFakeTimers()
        const made = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:made')
        const revoked = vi.spyOn(URL, 'revokeObjectURL').mockReturnValue()
        const clicked: { href: string; download: string }[] = []
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            clicked.push({ href: this.href, download: this.download })
        })
        const blob = new Blob(['a'], { type: 'image/png' })

        saveFile(blob, 'ABC-1-plan-2-flowchart-1.png')
        expect(made).toHaveBeenCalledWith(blob)
        expect(clicked).toEqual([{ href: 'blob:made', download: 'ABC-1-plan-2-flowchart-1.png' }])
        expect(document.querySelector('a')).toBeNull()
        expect(revoked).not.toHaveBeenCalled()
        vi.advanceTimersByTime(30_000)
        expect(revoked).toHaveBeenCalledWith('blob:made')
    })
})

describe('fileWords', () => {
    it.each([
        ['The loop: a tick, then a wait until the next one', 'the-loop-a-tick-then-a-wait-until-the-next-one'],
        ["A ticket's usual path, from ready to merged", 'a-ticket-s-usual-path-from-ready-to-merged'],
        ['  Café / naïve  ', 'cafe-naive'],
        ['../../etc/passwd', 'etc-passwd'],
        ['日本語', ''],
    ])('makes %j a name every system takes', (words, name) => {
        expect(fileWords(words)).toBe(name)
    })

    it('keeps at most 60 characters, never ending on a hyphen', () => {
        const name = fileWords(`${'word '.repeat(20)}end`)
        expect(name.length).toBeLessThanOrEqual(60)
        expect(name).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/u)
    })
})
