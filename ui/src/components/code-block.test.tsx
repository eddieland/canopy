import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CodeBlock } from './code-block'

// A code block's colors, which Shiki stops giving a line it has read for too long: a busy runner's (`untimedShiki`).
vi.mock(import('shiki/core'), async (importOriginal) =>
    (await import('@/test-utils')).untimedShiki(await importOriginal()),
)

beforeEach(() => {
    vi.stubGlobal('isSecureContext', true)
})

afterEach(() => {
    cleanup()
})

describe('CodeBlock', () => {
    it('copies its code from its corner as the fence holds it, with no newline after its last line', async () => {
        const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
        render(<CodeBlock lines={['uv tool install canopy', 'canopy loop']} lang="sh" />)
        fireEvent.click(screen.getByRole('button', { name: 'Copy code' }))
        await act(async () => {
            await Promise.resolve()
        })
        expect(write).toHaveBeenCalledWith('uv tool install canopy\ncanopy loop')
    })

    it('offers no copy where what holds it has actions of its own', () => {
        render(<CodeBlock lines={['flowchart LR']} lang="mermaid" copy={false} />)
        expect(screen.queryByRole('button')).toBeNull()
    })
})
