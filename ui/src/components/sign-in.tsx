import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import type { SubmitEvent } from 'react'

import { ApiError } from '@/api/client'
import { signIn } from '@/api/mutations'
import { keys, unsentQuery } from '@/api/queries'
import { Code } from '@/components/code'
import { Notice } from '@/components/notice'
import { Input } from '@/components/input'
import { Mark } from '@/components/mark'
import { Button } from '@/components/ui/button'
import { pageTitle } from '@/lib/page-title'

/**
 * Asks for the listener secret once (DESIGN §22). A right one sets a session cookie for 30 days; the secret itself is
 * never kept by the page. The hidden user name lets a password manager file the secret under canopy. Signed out by a
 * 401 to an action, it says the action was not sent; a reply being written is still in its box after signing in.
 */
export function SignIn() {
    const client = useQueryClient()
    const unsent = useQuery(unsentQuery).data === true
    const mutation = useMutation({
        mutationKey: keys.session,
        mutationFn: signIn,
        onSuccess: (session) => {
            client.setQueryData(keys.unsent, false)
            client.setQueryData(keys.session, session)
            void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'session' })
        },
    })

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        const secret = new FormData(event.currentTarget).get('secret')
        if (typeof secret === 'string' && secret) {
            mutation.mutate(secret)
        }
    }

    const wrong = mutation.error instanceof ApiError && mutation.error.status === 401
    return (
        <main className="grid min-h-dvh place-items-center p-6">
            <title>{pageTitle('Sign in', undefined)}</title>
            <form
                onSubmit={submit}
                aria-label="Sign in"
                className="flex w-full max-w-sm flex-col gap-4 rounded-md border bg-surface p-6"
            >
                <div className="flex items-center gap-2.5">
                    <Mark />
                    <span className="font-mono text-sm font-medium tracking-tight">canopy</span>
                </div>
                <div className="flex flex-col gap-1">
                    <h1 className="text-xl font-semibold tracking-tight">Sign in</h1>
                    <p className="text-sm text-muted-foreground">
                        Paste the listener secret. <Code>canopy secret</Code> prints it on the machine that runs the
                        loop.
                    </p>
                    {unsent && (
                        <p className="text-sm text-status-failed">
                            Your last action was not sent: sign in and send it again.
                        </p>
                    )}
                </div>
                <input type="text" name="username" value="canopy" autoComplete="username" readOnly hidden />
                <div className="flex flex-col gap-1.5">
                    <label htmlFor="secret" className="panel-label">
                        Listener secret
                    </label>
                    <Input
                        id="secret"
                        type="password"
                        name="secret"
                        required
                        autoComplete="current-password"
                        aria-invalid={wrong}
                    />
                </div>
                <Notice error={wrong ? new Error('That is not the listener secret.') : mutation.error} />
                <Button type="submit" disabled={mutation.isPending}>
                    <KeyRound />
                    {mutation.isPending ? 'Signing in' : 'Sign in'}
                </Button>
            </form>
        </main>
    )
}
