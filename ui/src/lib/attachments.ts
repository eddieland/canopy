import { ApiError } from '@/api/client'

/** An attachment's name, as runs see it: a plain file name, as `canopy.core.attachments.NAME_RE` has it. */
const NAME_RE = /^(?=[A-Za-z0-9._-]{1,100}$)[A-Za-z0-9][A-Za-z0-9._-]*$/u
const KIB = 1024

/**
 * The name an attachment gets from a file's, as `canopy attach` makes it when given none: each run of other characters
 * made `-`, a `-` before a `.` or at the end dropped, leading `.`, `_`, and `-` dropped, and cut to 100. Null when
 * nothing of the name is left.
 */
export function attachmentName(fileName: string): string | null {
    const last = fileName.replaceAll('\\', '/').split('/').at(-1) ?? ''
    const made = last
        .replaceAll(/[^A-Za-z0-9._-]+/gu, '-')
        .replaceAll(/-+(?=\.)|-+$/gu, '')
        .replace(/^[._-]+/u, '')
        .slice(0, 100)
    return NAME_RE.test(made) ? made : null
}

/** How large `size` bytes are, as the CLI says it: `12 KiB`, `12.5 KiB`, or `300 bytes`. */
export function sizeText(size: number): string {
    if (size % KIB === 0) {
        return `${size / KIB} KiB`
    }
    return size > KIB ? `${(size / KIB).toFixed(1)} KiB` : `${size} bytes`
}

/** The limits a subject's attachments are held to, as its page's read sends them. */
export interface AttachmentLimits {
    /** How many it may hold at once; 0 when attaching is off. */
    max_files: number
    /** The most bytes one may hold. */
    max_file_bytes: number
}

/**
 * Read `file` for an upload, refusing what the server would before sending it, with the CLI's guard and words: a name
 * nothing is left of, a file over the bound, and bytes that are not UTF-8. Any BOM is kept, so the text sent is the
 * file's bytes.
 *
 * @returns The name it is attached as, and its text.
 * @throws {ApiError} A refusal, as the server's would be.
 */
export async function readAttachment(file: File, limits: AttachmentLimits): Promise<{ name: string; text: string }> {
    const name = attachmentName(file.name)
    if (name === null) {
        throw refusal('bad_name', `${JSON.stringify(file.name)} has nothing in its name to name an attachment by`)
    }
    if (limits.max_files === 0) {
        throw refusal('too_many', 'attaching is off: policy.max_attachments is 0')
    }
    if (file.size > limits.max_file_bytes) {
        throw refusal('too_large', `${name} is over the ${sizeText(limits.max_file_bytes)} one attachment may hold`)
    }
    const bytes = await file.arrayBuffer()
    try {
        return { name, text: new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes) }
    } catch {
        throw refusal('not_text', `${name} is not UTF-8 text; export it as Markdown or plain text`)
    }
}

function refusal(guard: string, reason: string): ApiError {
    return new ApiError(409, { guard, reason })
}
