import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Paperclip, X } from 'lucide-react'
import { useRef, useState } from 'react'

import { attachFile, detachFile, refreshSubject } from '@/api/mutations'
import type { AttachmentSubject } from '@/api/mutations'
import type { Attachments as AttachmentsData } from '@/api/types'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { readAttachment, sizeText } from '@/lib/attachments'
import { attachedText, detachedText } from '@/lib/outcomes'
import { taskRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/**
 * The files the operator attached to a ticket or a task (DESIGN §22), which each of its later runs reads as data: each
 * by name and size, with a button that removes it, as `canopy detach` does, and Attach a file, which uploads one text
 * file, as `canopy attach` does, named from its own name. The page refuses what the server would, a file over the bound
 * or not UTF-8, before sending it, in the CLI's words; the server's guards decide the rest. Under the list, how much of
 * `policy`'s limits it holds. `closed`, for a stopped task, keeps the list and drops the button: it takes no more.
 */
export function Attachments({
    subject,
    attachments,
    closed = false,
    className,
}: {
    /** The ticket or task they are on. */
    subject: AttachmentSubject
    /** Its attachments, and the limits they are held to. */
    attachments: AttachmentsData
    /** Whether it takes no more, as a stopped task does. */
    closed?: boolean
    /** Classes for the section, such as its border. */
    className?: string
}) {
    const client = useQueryClient()
    const input = useRef<HTMLInputElement>(null)
    const [said, setSaid] = useState<string | null>(null)
    const ref = subject.kind === 'ticket' ? subject.key : taskRef(subject.id)
    const attach = useMutation({
        mutationFn: async (file: File) => {
            const { name, text } = await readAttachment(file, attachments)
            return attachFile(subject, name, text)
        },
        onMutate: () => setSaid(null),
        onSuccess: (attached) => {
            setSaid(attachedText(ref, attached))
            void refreshSubject(client, subject)
        },
    })
    const detach = useMutation({
        mutationFn: (name: string) => detachFile(subject, name),
        onMutate: () => setSaid(null),
        onSuccess: (detached) => {
            setSaid(detachedText(ref, detached))
            void refreshSubject(client, subject)
        },
    })
    const { items, max_files: maxFiles, max_total_bytes: maxTotal } = attachments
    const total = items.reduce((sum, a) => sum + a.size, 0)
    const pending = attach.isPending || detach.isPending
    const full = items.length >= maxFiles
    return (
        <section
            className={cn('flex flex-col gap-2 p-3', className)}
            aria-label="Attachments"
            data-testid="attachments"
        >
            <div className="flex items-center justify-between gap-2">
                <h3 className="panel-label">attachments</h3>
                {!closed && maxFiles > 0 && (
                    <>
                        <Button
                            variant="outline"
                            size="xs"
                            disabled={pending || full}
                            title={full ? `It holds ${maxFiles}, the most it may: remove one first.` : undefined}
                            onClick={() => input.current?.click()}
                        >
                            <Paperclip />
                            Attach a file
                        </Button>
                        <input
                            ref={input}
                            type="file"
                            className="sr-only"
                            tabIndex={-1}
                            aria-label="File to attach"
                            accept=".md,.markdown,.txt,.text,.rst,.adoc,.csv,.json,.yaml,.yml,.toml,text/*"
                            onChange={(event) => {
                                const file = event.currentTarget.files?.[0]
                                // Cleared, so choosing the same file again uploads it again.
                                event.currentTarget.value = ''
                                if (file !== undefined) {
                                    attach.mutate(file)
                                }
                            }}
                        />
                    </>
                )}
            </div>
            {items.length > 0 && (
                <ul className="flex flex-col gap-1">
                    {items.map((a) => (
                        <li key={a.name} className="flex items-center gap-2 font-mono text-xs">
                            <span className="min-w-0 truncate" title={a.name}>
                                {a.name}
                            </span>
                            <span className="shrink-0 text-muted-foreground">{sizeText(a.size)}</span>
                            <Button
                                variant="ghost"
                                size="icon-xs"
                                className="ml-auto"
                                aria-label={`Remove ${a.name}`}
                                disabled={pending}
                                onClick={() => detach.mutate(a.name)}
                            >
                                <X />
                            </Button>
                        </li>
                    ))}
                </ul>
            )}
            <p className="text-xs text-muted-foreground">{heldText(items.length, maxFiles, total, maxTotal)}</p>
            <Notice error={attach.error ?? detach.error}>{said}</Notice>
        </section>
    )
}

/** How much of its limits a subject's attachments hold, or that attaching is off. */
function heldText(files: number, maxFiles: number, total: number, maxTotal: number): string {
    if (maxFiles === 0) {
        return 'Attaching is off: policy.max_attachments is 0.'
    }
    const held = `${files} of ${maxFiles} files, ${sizeText(total)} of ${sizeText(maxTotal)}.`
    return `${held} Text only; its runs read them as data.`
}
