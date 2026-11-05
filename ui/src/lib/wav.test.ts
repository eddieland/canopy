import { describe, expect, it } from 'vitest'

import { encodeWav, SPEECH_RATE } from './wav'

function header(bytes: Uint8Array): { riff: string; wave: string; format: number[]; data: number } {
    const view = new DataView(bytes.buffer)
    const ascii = (from: number) => String.fromCodePoint(...bytes.slice(from, from + 4))
    return {
        riff: ascii(0),
        wave: ascii(8),
        // PCM, channels, rate, bytes a second, bytes a frame, bits a sample.
        format: [
            view.getUint16(20, true),
            view.getUint16(22, true),
            view.getUint32(24, true),
            view.getUint32(28, true),
            view.getUint16(32, true),
            view.getUint16(34, true),
        ],
        data: view.getUint32(40, true),
    }
}

describe('encodeWav', () => {
    it('writes the 16-bit mono PCM header the server checks', () => {
        const bytes = encodeWav(new Float32Array(3), SPEECH_RATE)
        expect(bytes).toHaveLength(44 + 6)
        expect(header(bytes)).toEqual({
            riff: 'RIFF',
            wave: 'WAVE',
            format: [1, 1, 16_000, 32_000, 2, 16],
            data: 6,
        })
        expect(new DataView(bytes.buffer).getUint32(4, true)).toBe(bytes.length - 8)
    })

    it('scales each sample to 16 bits, clipping one past either end', () => {
        const bytes = encodeWav(Float32Array.from([0, 1, -1, 0.5, 2, -3]), 8000)
        const view = new DataView(bytes.buffer)
        const samples = Array.from({ length: 6 }, (_, i) => view.getInt16(44 + i * 2, true))
        expect(samples).toEqual([0, 32_767, -32_768, 16_383, 32_767, -32_768])
    })
})
