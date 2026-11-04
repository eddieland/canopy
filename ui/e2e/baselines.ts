import { open, readdir } from 'node:fs/promises'
import { join } from 'node:path'

// What a Git LFS pointer file starts with, where the image it stands for has not been fetched.
const LFS_POINTER = 'version https://git-lfs'

/**
 * Playwright's global setup: fails the run before any test when the screenshot baselines are Git LFS pointers, not
 * images, so a checkout without them gets one error naming the fix rather than a failed comparison per screenshot.
 */
export default async function checkBaselines(): Promise<void> {
    const dir = import.meta.dirname
    const snapshots = (await readdir(dir)).filter((name) => name.endsWith('-snapshots'))
    for (const folder of snapshots) {
        const images = (await readdir(join(dir, folder))).filter((name) => name.endsWith('.png'))
        const checks = await Promise.all(images.map((name) => startsWith(join(dir, folder, name), LFS_POINTER)))
        const image = images.find((_, index) => checks[index])
        if (image !== undefined) {
            throw new Error(
                `${folder}/${image} is a Git LFS pointer, not an image: the screenshot baselines are in Git LFS. ` +
                    'Install git-lfs, then run `git lfs install && git lfs pull` in the repository.',
            )
        }
    }
}

/** Whether the file at path begins with prefix. */
async function startsWith(path: string, prefix: string): Promise<boolean> {
    const file = await open(path)
    try {
        const buffer = Buffer.alloc(prefix.length)
        await file.read(buffer, 0, prefix.length, 0)
        return buffer.toString('utf8') === prefix
    } finally {
        await file.close()
    }
}
