import { describe, expect, it } from 'vitest'

import { directoryTail, sessionName } from './sessions'

describe('directoryTail', () => {
    it.each([
        ['/home/op/acme/infra', '…/acme/infra'],
        ['/home/op/beta/.treehouse/api-5d1e0b2c/1/api', '…/1/api'],
        ['/home/op', '/home/op'],
        ['/srv', '/srv'],
        ['/home/op/notes/', '…/op/notes'],
    ])('keeps the last two parts of %s', (directory, tail) => {
        expect(directoryTail(directory)).toBe(tail)
    })
})

describe('sessionName', () => {
    it('is the title, or the id for a session with none', () => {
        expect(sessionName({ title: 'Fix the deploy', session_id: 'ses_1' })).toBe('Fix the deploy')
        expect(sessionName({ title: null, session_id: 'ses_1' })).toBe('session ses_1')
    })
})
