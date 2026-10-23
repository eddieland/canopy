import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { mockNoAttachments } from '@/api/mocks'
import type { AttachmentSubject } from '@/api/mutations'
import type { Attachments as AttachmentsData } from '@/api/types'
import { attachmentName, sizeText } from '@/lib/attachments'

import { Attachments } from './attachments'

const DOC = '# Importer\n\nShard the queue by tenant.\n'
const HELD: AttachmentsData = {
    ...mockNoAttachments,
    items: [{ name: 'design.md', size: 39, channel: 'cli', added_at: '2026-10-08T11:00:00Z' }],
}

// Every write the section sends, and what the server stand-in answers each.
let sent: { method: string; path: string; type: string | null; body: string }[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        const path = new URL(request.url).pathname
        sent.push({
            method: request.method,
            path,
            type: request.headers.get('content-type'),
            body: await request.text(),
        })
        if (answer !== undefined) {
            return answer
        }
        const name = decodeURIComponent(path.split('/').at(-1) ?? '')
        if (request.method === 'DELETE') {
            return Response.json({ name })
        }
        return Response.json({ attachment: { name, size: 39, channel: 'web', added_at: '2026-10-08T12:00:00Z' } })
    },
}

beforeEach(() => {
    sent = []
    answer = undefined
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderSection(attachments: AttachmentsData = HELD, closed = false, subject?: AttachmentSubject) {
    return render(
        <QueryClientProvider client={new QueryClient()}>
            <Attachments subject={subject ?? { kind: 'task', id: 7 }} attachments={attachments} closed={closed} />
        </QueryClientProvider>,
    )
}

function choose(file: File) {
    fireEvent.change(screen.getByLabelText('File to attach'), { target: { files: [file] } })
}

describe('Attachments', () => {
    it('lists each file with its size and says how much of the limits it holds', () => {
        renderSection()
        expect(screen.getByRole('listitem').textContent).toBe('design.md39 bytes')
        expect(screen.getByText(/^1 of 5 files, 39 bytes of 1024 KiB/u)).toBeTruthy()
        expect(screen.getByRole('button', { name: 'Attach a file' })).toBeTruthy()
    })

    it("uploads a text file's bytes under a plain name, and says what it did in the CLI's words", async () => {
        renderSection(mockNoAttachments)
        choose(new File([DOC], 'Importer design (v2).md', { type: 'text/markdown' }))
        const said = 'Attached Importer-design-v2.md (39 bytes) to task:7; its next run reads it.'
        expect(await screen.findByText(said)).toBeTruthy()
        expect(sent).toEqual([
            { method: 'PUT', path: '/api/tasks/7/attachments/Importer-design-v2.md', type: 'text/plain', body: DOC },
        ])
    })

    it('refuses a file that is not UTF-8 before sending it, naming the guard as the CLI does', async () => {
        renderSection(mockNoAttachments)
        choose(new File([new Uint8Array([37, 80, 68, 70, 255, 254])], 'spec.pdf'))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (not_text): spec.pdf is not UTF-8 text; export it as Markdown or plain text',
        )
        expect(sent).toEqual([])
    })

    it('refuses a file over the bound before reading it', async () => {
        renderSection({ ...mockNoAttachments, max_file_bytes: 4 })
        choose(new File(['12345'], 'notes.txt'))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (too_large): notes.txt is over the 4 bytes one attachment may hold',
        )
        expect(sent).toEqual([])
    })

    it("shows the server's refusal", async () => {
        answer = Response.json({ detail: { guard: 'taken', reason: 'task:7 already has design.md' } }, { status: 409 })
        renderSection(mockNoAttachments)
        choose(new File([DOC], 'design.md'))
        expect((await screen.findByRole('alert')).textContent).toBe('refused (taken): task:7 already has design.md')
    })

    it('removes one, as canopy detach does, on a ticket by its key', async () => {
        renderSection(HELD, false, { kind: 'ticket', key: 'ABC-1' })
        fireEvent.click(screen.getByRole('button', { name: 'Remove design.md' }))
        expect(await screen.findByText('Removed design.md from ABC-1.')).toBeTruthy()
        expect(sent.map((s) => [s.method, s.path])).toEqual([['DELETE', '/api/tickets/ABC-1/attachments/design.md']])
    })

    it('keeps no attach button on a stopped task, or when it holds as many as it may, or attaching is off', () => {
        renderSection(HELD, true)
        expect(screen.queryByRole('button', { name: 'Attach a file' })).toBeNull()
        cleanup()
        renderSection({ ...HELD, max_files: 1 })
        expect(screen.getByRole('button', { name: 'Attach a file' }).hasAttribute('disabled')).toBe(true)
        cleanup()
        renderSection({ ...mockNoAttachments, max_files: 0 })
        expect(screen.queryByRole('button', { name: 'Attach a file' })).toBeNull()
        expect(screen.getByText('Attaching is off: policy.max_attachments is 0.')).toBeTruthy()
    })
})

describe('attachmentName', () => {
    it('makes a plain name from a file name, as canopy attach does', () => {
        expect(attachmentName('Importer design (v2).md')).toBe('Importer-design-v2.md')
        expect(attachmentName('C:\\Users\\me\\spec v1.txt')).toBe('spec-v1.txt')
        expect(attachmentName('.hidden.md')).toBe('hidden.md')
        expect(attachmentName('résumé notes')).toBe('r-sum-notes')
        expect(attachmentName('()')).toBeNull()
    })
})

describe('sizeText', () => {
    it('says sizes as the CLI does', () => {
        expect([sizeText(300), sizeText(2048), sizeText(1536)]).toEqual(['300 bytes', '2 KiB', '1.5 KiB'])
    })
})
