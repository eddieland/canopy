import { clsx } from 'clsx'
import type { ClassValue } from 'clsx'
import type { ReactNode } from 'react'
import { extendTailwindMerge } from 'tailwind-merge'

// The theme's sizes and shadows that are not on Tailwind's t-shirt scale (`--text-*` and `--shadow-*` in
// src/styles/tokens.css). Unknown to tailwind-merge, `text-code` would read as a color, so `cn('text-code',
// 'text-muted-foreground')` would drop the size; utils.test.ts holds this list to the stylesheet.
const twMerge = extendTailwindMerge({
    extend: {
        theme: {
            text: ['code'],
            shadow: ['panel', 'float', 'action', 'action-pressed', 'bubble', 'chip', 'selected'],
        },
    },
})

/** Joins class names, letting a later Tailwind utility override an earlier one of the same kind. */
export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs))
}

/** Whether React renders nothing for `node`: null, undefined, a boolean, or the empty string. */
export function isBlank(node: ReactNode): node is null | undefined | boolean | '' {
    return node === null || node === undefined || typeof node === 'boolean' || node === ''
}
