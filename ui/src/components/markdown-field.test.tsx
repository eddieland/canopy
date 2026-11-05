import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createRef, StrictMode, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { dictate } from '@/api/mutations'
import { DictationContext } from '@/hooks/use-dictation'
import { speechWav } from '@/lib/wav'

import { MarkdownField } from './markdown-field'
import type { MarkdownPreview } from './markdown-field'

// The server's transcription and the browser's resampling: what the field does with each is what is tested here.
vi.mock(import('@/api/mutations'), async (importOriginal) => ({
    ...(await importOriginal()),
    dictate: vi.fn<typeof dictate>(),
}))
vi.mock(import('@/lib/wav'), async (importOriginal) => ({
    ...(await importOriginal()),
    speechWav: vi.fn<typeof speechWav>(),
}))

afterEach(cleanup)

// The field as a form holds it, starting from `initial`.
function Holder({
    initial,
    preview,
    maxLength,
    onKeyDown,
}: {
    initial: string
    preview?: MarkdownPreview
    maxLength?: number
    onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void
}) {
    const [value, setValue] = useState(initial)
    return (
        <MarkdownField
            aria-label="Reply"
            value={value}
            onValueChange={setValue}
            preview={preview}
            maxLength={maxLength}
            onKeyDown={onKeyDown}
        />
    )
}

function field(): HTMLTextAreaElement {
    return screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' })
}

function select(start: number, end = start) {
    field().setSelectionRange(start, end)
}

describe('MarkdownField', () => {
    it('offers only what the conversation draws, each with its shortcut', () => {
        render(<Holder initial="" />)
        const toolbar = screen.getByRole('toolbar', { name: 'Formatting' })
        const names = ['Bold', 'Code', 'Heading', 'Bulleted list', 'Numbered list', 'Code block']
        for (const name of names) {
            expect(screen.getByRole('button', { name })).toBeDefined()
        }
        expect(toolbar.textContent).toContain('Preview')
        expect(screen.getByRole('button', { name: 'Bold' }).getAttribute('aria-keyshortcuts')).toMatch(/\+B$/u)
    })

    it('formats the selection from the toolbar and keeps it selected', () => {
        render(<Holder initial="use the v2 API" />)
        select(4, 14)
        fireEvent.click(screen.getByRole('button', { name: 'Bold' }))
        expect(field().value).toBe('use **the v2 API**')
        expect([field().selectionStart, field().selectionEnd]).toEqual([6, 16])

        fireEvent.click(screen.getByRole('button', { name: 'Bulleted list' }))
        expect(field().value).toBe('- use **the v2 API**')
    })

    it('formats from the keyboard, and continues a list on Enter', () => {
        render(<Holder initial="- first" />)
        select(7)
        fireEvent.keyDown(field(), { key: 'Enter' })
        expect(field().value).toBe('- first\n- ')
        fireEvent.keyDown(field(), { key: 'Enter' })
        expect(field().value).toBe('- first\n')

        fireEvent.keyDown(field(), { key: 'e', ctrlKey: true })
        expect(field().value).toBe('- first\n``')
    })

    it('leaves Enter to a key handler that took it, such as the send key', () => {
        render(<Holder initial="- first" onKeyDown={(event) => event.preventDefault()} />)
        select(7)
        fireEvent.keyDown(field(), { key: 'Enter' })
        expect(field().value).toBe('- first')
    })

    it('gives a ref the caller passes the textarea, and still formats through its own', () => {
        const caller = createRef<HTMLTextAreaElement>()
        function WithRef() {
            const [value, setValue] = useState('word')
            return <MarkdownField aria-label="Reply" ref={caller} value={value} onValueChange={setValue} />
        }
        render(<WithRef />)
        expect(caller.current).toBe(field())
        select(0, 4)
        fireEvent.click(screen.getByRole('button', { name: 'Code' }))
        expect(field().value).toBe('`word`')
    })

    it('previews the text as it will read, and goes back to it', () => {
        render(<Holder initial="**Use** the `v2` API" />)
        fireEvent.click(screen.getByRole('radio', { name: 'Preview' }))
        const preview = screen.getByRole('region', { name: 'Preview' })
        expect(preview.textContent).toBe('Use the v2 API')
        expect(screen.getByText('Use').tagName).toBe('STRONG')
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Bold' }).disabled).toBe(true)

        fireEvent.click(screen.getByRole('radio', { name: 'Write' }))
        expect(screen.queryByRole('region', { name: 'Preview' })).toBeNull()
        expect(field().value).toBe('**Use** the `v2` API')
    })

    it('switches back from the preview on the same key, from the toolbar the focus is in', () => {
        render(<Holder initial="text" />)
        fireEvent.keyDown(field(), { key: 'P', ctrlKey: true, shiftKey: true })
        expect(screen.getByRole('region', { name: 'Preview' })).toBeDefined()
        fireEvent.keyDown(screen.getByRole('radio', { name: 'Write' }), { key: 'P', ctrlKey: true, shiftKey: true })
        expect(screen.queryByRole('region', { name: 'Preview' })).toBeNull()
        expect(field().hidden).toBe(false)
    })

    it('says when there is nothing to preview', () => {
        render(<Holder initial="  " />)
        fireEvent.click(screen.getByRole('radio', { name: 'Preview' }))
        expect(screen.getByRole('region', { name: 'Preview' }).textContent).toBe('nothing to preview yet')
    })

    it('previews live beside the text, with no toggle', () => {
        render(<Holder initial="- one" preview="live" />)
        expect(screen.queryByRole('radio', { name: 'Preview' })).toBeNull()
        expect(screen.getByRole('region', { name: 'Preview' }).textContent).toBe('one')
        fireEvent.change(field(), { target: { value: '- one\n- two' } })
        expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual(['one', 'two'])
    })
})

// The browser's recorder: it records until stopped, then hands over what it recorded.
class FakeRecorder {
    static made: FakeRecorder[] = []
    state: RecordingState = 'inactive'
    mimeType = 'audio/webm'
    ondataavailable: ((event: { data: Blob }) => void) | null = null
    onstop: (() => void) | null = null

    stream: MediaStream

    constructor(stream: MediaStream) {
        this.stream = stream
        FakeRecorder.made.push(this)
    }

    start() {
        this.state = 'recording'
    }

    stop() {
        this.state = 'inactive'
        this.ondataavailable?.({ data: new Blob(['speech']) })
        this.onstop?.()
    }
}

// The field where the server offers dictation, starting from `initial`, holding at most `maxLength` characters.
function offered(initial: string, maxLength?: number) {
    return render(
        <DictationContext value>
            <Holder initial={initial} maxLength={maxLength} />
        </DictationContext>,
    )
}

// The operator presses the microphone, sees the clock start, and presses it again to stop.
async function speak() {
    await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Dictate' }))
        await Promise.resolve()
    })
    expect(screen.getByRole('timer', { name: 'Recorded' }).textContent).toBe('0:00')
    await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Stop dictating' }))
        await Promise.resolve()
    })
}

describe('MarkdownField dictation', () => {
    const track = { stop: vi.fn<() => void>() }
    const getUserMedia = vi.fn<(constraints: MediaStreamConstraints) => Promise<MediaStream>>()
    const wav = new Blob(['wav'], { type: 'audio/wav' })

    beforeEach(() => {
        FakeRecorder.made = []
        track.stop.mockClear()
        getUserMedia.mockReset()
        getUserMedia.mockResolvedValue({ getTracks: () => [track] } as unknown as MediaStream)
        vi.stubGlobal('isSecureContext', true)
        vi.stubGlobal('MediaRecorder', FakeRecorder)
        Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia }, configurable: true })
        vi.mocked(speechWav).mockResolvedValue(wav)
        vi.mocked(dictate).mockReset()
    })

    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('shows no microphone where the server offers no dictation', () => {
        render(<Holder initial="" />)
        expect(screen.queryByRole('button', { name: 'Dictate' })).toBeNull()
    })

    it('puts what was heard where the cursor is, and lets go of the microphone', async () => {
        vi.mocked(dictate).mockResolvedValue({ text: 'shard by tenant', seconds: 2 })
        offered('Ship it, then')
        select(4)
        await speak()
        expect(await screen.findByRole('button', { name: 'Dictate' })).toBeDefined()
        expect(field().value).toBe('Ship shard by tenant it, then')
        expect(vi.mocked(speechWav).mock.calls[0]?.[0]).toBeInstanceOf(Blob)
        expect(vi.mocked(dictate)).toHaveBeenCalledWith(wav)
        expect(track.stop).toHaveBeenCalled()
        expect(getUserMedia.mock.calls[0]?.[0].audio).toMatchObject({ channelCount: 1, noiseSuppression: true })
    })

    it('keeps a space between what was heard and a word right after the cursor', async () => {
        vi.mocked(dictate).mockResolvedValue({ text: 'first,', seconds: 1 })
        offered('then ship it')
        select(0)
        await speak()
        await screen.findByRole('button', { name: 'Dictate' })
        expect(field().value).toBe('first, then ship it')
    })

    it('puts no more in than the box holds, and says how much was left out', async () => {
        vi.mocked(dictate).mockResolvedValue({ text: 'shard by tenant', seconds: 2 })
        offered('Note: ', 15)
        select(6)
        await speak()
        expect((await screen.findByText(/^The box was full/u)).textContent).toBe(
            'The box was full: the last 6 characters of what was heard were left out.',
        )
        expect(field().value).toBe('Note: shard by ')
    })

    it('records under StrictMode, which mounts the field, cleans it up, and mounts it again', async () => {
        vi.mocked(dictate).mockResolvedValue({ text: 'shard by tenant', seconds: 2 })
        render(
            <StrictMode>
                <DictationContext value>
                    <Holder initial="" />
                </DictationContext>
            </StrictMode>,
        )
        await speak()
        await screen.findByRole('button', { name: 'Dictate' })
        expect(field().value).toBe('shard by tenant')
    })

    it('lets go of a microphone the browser grants after the field has gone', async () => {
        let grant: ((stream: MediaStream) => void) | undefined
        getUserMedia.mockReturnValue(
            new Promise((resolve) => {
                grant = resolve
            }),
        )
        const { unmount } = offered('')
        fireEvent.click(screen.getByRole('button', { name: 'Dictate' }))
        const asking = screen.getByRole<HTMLButtonElement>('button', { name: 'Dictate' })
        expect(asking.disabled).toBe(true)
        fireEvent.click(asking)
        expect(getUserMedia).toHaveBeenCalledTimes(1)
        unmount()
        await act(async () => {
            grant?.({ getTracks: () => [track] } as unknown as MediaStream)
            await Promise.resolve()
        })
        expect(track.stop).toHaveBeenCalled()
        expect(FakeRecorder.made).toEqual([])
    })

    it('says the server refused, naming its guard, and leaves the text as it was', async () => {
        const said = { guard: 'failed', reason: 'whisper-cli exited 3: model file not found' }
        vi.mocked(dictate).mockRejectedValue(new ApiError(409, said))
        offered('Ship it')
        await speak()
        const alert = await screen.findByRole('alert')
        expect(alert.textContent).toBe('refused (failed): whisper-cli exited 3: model file not found')
        expect(field().value).toBe('Ship it')
    })

    it('says so when nothing was heard', async () => {
        vi.mocked(dictate).mockResolvedValue({ text: '', seconds: 1 })
        offered('')
        await speak()
        expect((await screen.findByText('Nothing was heard in that recording.')).textContent).toBeDefined()
        expect(field().value).toBe('')
    })

    it('says why when the browser keeps the microphone from the page', async () => {
        getUserMedia.mockRejectedValue(new DOMException('Permission denied', 'NotAllowedError'))
        offered('')
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Dictate' }))
            await Promise.resolve()
        })
        expect((await screen.findByRole('alert')).textContent).toMatch(/^the browser was not allowed to use the mic/u)
        expect(FakeRecorder.made).toEqual([])
    })

    it('is off, saying why, on a page that is not over HTTPS or localhost', () => {
        vi.stubGlobal('isSecureContext', false)
        offered('')
        const button = screen.getByRole<HTMLButtonElement>('button', { name: 'Dictate' })
        expect(button.disabled).toBe(true)
        expect(button.title).toMatch(/needs this page over HTTPS or localhost/u)
    })
})
