import { useMeasure } from '@/hooks/use-measure'

/**
 * Whether a piece of fun fits the room the layout leaves it, so it can step out rather than squeeze or cover what is
 * beside it (DESIGN.md, "Fun"). `fits` judges the slot, the element the returned ref is put on, and is asked again
 * each time the slot or anything directly in it changes size: false when nothing fits, else how it fits (`true`, or
 * one of the ways the caller tells apart). Nothing fits until it has been measured, which happens before the first
 * paint, so what does not fit never flashes in.
 */
export function useFits<T>(
    fits: (slot: HTMLElement) => T | false,
): [(slot: HTMLElement | null) => () => void, T | false] {
    return useMeasure<T | false>(fits, false, { children: true })
}
