import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'
import { keys } from '@/api/queries'

import { createQueryClient } from './query-client'

describe('createQueryClient', () => {
    it('signs the page out when a request finds no session', async () => {
        const client = createQueryClient()
        client.setQueryData(keys.session, { signed_in: true, token: 't' })
        await client
            .query({
                queryKey: ['runs'],
                queryFn: () => Promise.reject(new ApiError(401, 'sign in with the listener secret')),
            })
            .catch(() => {})
        expect(client.getQueryData(keys.session)).toEqual({ signed_in: false, token: null })
    })
})
