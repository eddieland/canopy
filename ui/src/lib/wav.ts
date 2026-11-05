// A recording made the WAV the server's dictation takes (DESIGN §22): 16-bit mono PCM at 16 kHz, which every speech
// model reads without a decoder of its own. The browser records in its own format (Opus in WebM in Chrome and
// Firefox, AAC in MP4 in Safari), so the page decodes it and resamples it here, and the loop's machine needs no ffmpeg.

/** The sample rate a recording is sent at, as the server checks it. */
export const SPEECH_RATE = 16_000

const HEADER_BYTES = 44

/**
 * `recorded`, a recording in whatever format the browser made it, as a 16-bit mono WAV at `rate`: decoded, its
 * channels mixed down, and resampled by the browser's own audio graph. Rejects with an `Error` in canopy's words when
 * the browser cannot decode it.
 */
export async function speechWav(recorded: Blob, rate: number = SPEECH_RATE): Promise<Blob> {
    const context = new AudioContext()
    let decoded: AudioBuffer
    try {
        decoded = await context.decodeAudioData(await recorded.arrayBuffer())
    } catch {
        throw new Error('this browser could not read back its own recording')
    } finally {
        await context.close()
    }
    // One channel at `rate`: the destination mixes the source's channels down, and the context resamples it.
    const offline = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate)
    const source = offline.createBufferSource()
    source.buffer = decoded
    source.connect(offline.destination)
    source.start()
    const rendered = await offline.startRendering()
    return new Blob([encodeWav(rendered.getChannelData(0), rate)], { type: 'audio/wav' })
}

/** `samples`, from -1 to 1, as the bytes of a 16-bit mono PCM WAV at `rate`; a sample past either end is clipped. */
export function encodeWav(samples: Float32Array, rate: number): Uint8Array<ArrayBuffer> {
    const bytes = new ArrayBuffer(HEADER_BYTES + samples.length * 2)
    const view = new DataView(bytes)
    const ascii = new TextEncoder()
    const text = (at: number, word: string) => new Uint8Array(bytes, at, word.length).set(ascii.encode(word))
    text(0, 'RIFF')
    view.setUint32(4, bytes.byteLength - 8, true)
    text(8, 'WAVE')
    text(12, 'fmt ')
    // The format chunk: its size, PCM, one channel, the rate, bytes a second, bytes a frame, and bits a sample.
    view.setUint32(16, 16, true)
    view.setUint16(20, 1, true)
    view.setUint16(22, 1, true)
    view.setUint32(24, rate, true)
    view.setUint32(28, rate * 2, true)
    view.setUint16(32, 2, true)
    view.setUint16(34, 16, true)
    text(36, 'data')
    view.setUint32(40, samples.length * 2, true)
    for (const [i, sample] of samples.entries()) {
        const clipped = Math.max(-1, Math.min(1, sample))
        view.setInt16(HEADER_BYTES + i * 2, clipped < 0 ? clipped * 32_768 : clipped * 32_767, true)
    }
    return new Uint8Array(bytes)
}
