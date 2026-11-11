import { afterEach, describe, expect, it, vi } from 'vitest'

import { saveFile } from './save-file'

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
        const blob = new Blob(['# Plan\n'], { type: 'text/markdown' })

        saveFile(blob, '412-APPROVED-export-reports-as-csv.md')
        expect(made).toHaveBeenCalledWith(blob)
        expect(clicked).toEqual([{ href: 'blob:made', download: '412-APPROVED-export-reports-as-csv.md' }])
        expect(document.querySelector('a')).toBeNull()
        expect(revoked).not.toHaveBeenCalled()
        vi.advanceTimersByTime(30_000)
        expect(revoked).toHaveBeenCalledWith('blob:made')
    })
})
