import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'

import { SignIn } from './sign-in'

// Every secret sent, and what the server stand-in answers it, once `release` lets it.
let sent: unknown[] = []
let answer: Response | undefined
let held: Promise<void> = Promise.resolve()

const server: Middleware = {
    async onRequest({ request }) {
        sent.push(await request.json())
        await held
        return answer ?? Response.json({ signed_in: true, token: 'tok' })
    },
}

beforeEach(() => {
    sent = []
    answer = undefined
    held = Promise.resolve()
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

// Holds the server stand-in's answers until the function returned is called.
function holdAnswers(): () => void {
    let release: (() => void) | undefined
    held = new Promise((resolve) => {
        release = resolve
    })
    return () => release?.()
}

function renderSignIn(client = new QueryClient()) {
    return render(
        <QueryClientProvider client={client}>
            <SignIn />
        </QueryClientProvider>,
    )
}

function signInWith(secret: string) {
    fireEvent.change(screen.getByLabelText('Listener secret'), { target: { value: secret } })
    fireEvent.submit(screen.getByRole('form', { name: 'Sign in' }))
}

describe('SignIn', () => {
    it('sends the secret once, signs the page in, and reads everything else again', async () => {
        const client = new QueryClient()
        client.setQueryData(keys.session, { signed_in: false, token: null })
        client.setQueryData(keys.tickets, [])
        renderSignIn(client)

        signInWith('s3cret')
        await waitFor(() => {
            expect(client.getQueryData(keys.session)).toEqual({ signed_in: true, token: 'tok' })
        })
        expect(sent).toEqual([{ secret: 's3cret' }])
        expect(client.getQueryState(keys.tickets)?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.session)?.isInvalidated).toBe(false)
    })

    it('sends nothing without a secret', () => {
        renderSignIn()
        signInWith('')
        expect(sent).toEqual([])
    })

    it('says so on its button while it signs in, which cannot be pressed again until it ends', async () => {
        const release = holdAnswers()
        renderSignIn()
        signInWith('s3cret')
        const button = await screen.findByRole<HTMLButtonElement>('button', { name: 'Signing in' })
        expect(button.disabled).toBe(true)

        release()
        expect((await screen.findByRole<HTMLButtonElement>('button', { name: 'Sign in' })).disabled).toBe(false)
    })

    it('says a wrong secret is not the listener secret, and marks the field', async () => {
        answer = Response.json({ detail: 'bad secret' }, { status: 401 })
        renderSignIn()
        const field = screen.getByLabelText('Listener secret')
        expect(field.getAttribute('aria-invalid')).toBe('false')

        signInWith('nope')
        expect((await screen.findByRole('alert')).textContent).toBe('That is not the listener secret.')
        expect(field.getAttribute('aria-invalid')).toBe('true')
    })

    it('says any other failure in its own words, the field not marked', async () => {
        answer = Response.json({ detail: 'the journal is busy' }, { status: 503 })
        renderSignIn()
        signInWith('s3cret')
        expect((await screen.findByRole('alert')).textContent).toBe('the journal is busy')
        expect(screen.getByLabelText('Listener secret').getAttribute('aria-invalid')).toBe('false')
    })
})
