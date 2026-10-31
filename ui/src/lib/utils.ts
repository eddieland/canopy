import { clsx } from 'clsx'
import type { ClassValue } from 'clsx'
import type { ReactNode } from 'react'
import { twMerge } from 'tailwind-merge'

/** Joins class names, letting a later Tailwind utility override an earlier one of the same kind. */
export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs))
}

/** Whether React renders nothing for `node`: null, undefined, a boolean, or the empty string. */
export function isBlank(node: ReactNode): node is null | undefined | boolean | '' {
    return node === null || node === undefined || typeof node === 'boolean' || node === ''
}
