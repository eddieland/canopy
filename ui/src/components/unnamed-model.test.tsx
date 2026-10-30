import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { NONE_RUNS_HINT, unnamedHint, UNREAD_RUNS_HINT } from '@/lib/models'

import { UnnamedModel } from './unnamed-model'

afterEach(cleanup)

describe('UnnamedModel', () => {
    it('says unread for the runs whose sessions canopy has yet to read, never none', () => {
        render(<UnnamedModel unread />)
        expect(screen.getByText('unread')).toBeDefined()
        expect(screen.queryByText(/none/u)).toBeNull()
        expect(unnamedHint(true)).toBe(UNREAD_RUNS_HINT)
    })

    it('says none with why for the runs read that named no model', () => {
        render(<UnnamedModel unread={false} />)
        expect(screen.getByText('none: no session named one')).toBeDefined()
        expect(screen.queryByText('unread')).toBeNull()
        expect(unnamedHint(false)).toBe(NONE_RUNS_HINT)
    })
})
