import { useMutation, useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import type { FormEvent } from 'react'

import { ApiError } from '@/api/client'
import { signIn } from '@/api/mutations'
import { keys } from '@/api/queries'
import { Notice } from '@/components/notice'
import { Input } from '@/components/input'
import { Mark } from '@/components/shell/mark'
import { Button } from '@/components/ui/button'

/**
 * Asks for the listener secret once (D082). A right one sets a session cookie for 30 days; the secret itself is
 * never kept by the page. The hidden user name lets a password manager file the secret under canopy.
 */
export function SignIn() {
    const client = useQueryClient()
    const mutation = useMutation({
        mutationFn: signIn,
        onSuccess: (session) => {
            client.setQueryData(keys.session, session)
            void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'session' })
        },
    })

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        const secret = new FormData(event.currentTarget).get('secret')
        if (typeof secret === 'string' && secret) mutation.mutate(secret)
    }

    const wrong = mutation.error instanceof ApiError && mutation.error.status === 401
    return (
        <main className="grid min-h-dvh place-items-center p-6">
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
                        Paste the listener secret. <code className="font-mono text-xs">canopy secret</code> prints it on
                        the machine that runs the loop.
                    </p>
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
