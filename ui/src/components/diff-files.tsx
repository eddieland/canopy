import { Check } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { linesText } from '@/lib/run-changes'

/** A file of a diff as its list names it. */
export interface ListedFile {
    /** The file's index in the diff. */
    index: number
    /** Its path in the repository. */
    path: string
    /** How many lines its diff adds. */
    added: number
    /** How many lines its diff removes. */
    removed: number
    /** How many cards sit on it: a review's findings, a PR's threads. */
    cards: number
    /** Whether the operator marked it viewed. */
    viewed: boolean
}

/**
 * The list of a diff's files, opened from `children`, a button: each file with a check once viewed, its path, how
 * many `cards` sit on it, named one and many, and the lines it adds and removes. A field narrows it by what a path
 * holds, and picking a file closes the list and tells `onPick` its index.
 */
export function FileList({
    files,
    cards,
    onPick,
    children,
}: {
    files: readonly ListedFile[]
    cards: readonly [string, string]
    onPick: (index: number) => void
    children: ReactNode
}) {
    const [open, setOpen] = useState(false)
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>{children}</PopoverTrigger>
            <PopoverContent align="start" className="w-[min(40rem,90vw)] p-0">
                {/* Found anywhere in a path, as every picker finds a name, rather than by cmdk's fuzzy match. */}
                <Command label="Find a file" filter={holds}>
                    <CommandInput placeholder="Find a file" />
                    <CommandList label="Files">
                        <CommandEmpty>No file with that in its path.</CommandEmpty>
                        {files.map((file) => (
                            <FileItem
                                key={file.index}
                                file={file}
                                cards={cards}
                                onSelect={() => {
                                    setOpen(false)
                                    onPick(file.index)
                                }}
                            />
                        ))}
                    </CommandList>
                </Command>
            </PopoverContent>
        </Popover>
    )
}

function FileItem({
    file,
    cards,
    onSelect,
}: {
    file: ListedFile
    cards: readonly [string, string]
    onSelect: () => void
}) {
    const slash = file.path.lastIndexOf('/') + 1
    const [plus, minus] = linesText(file.added, file.removed)
    return (
        // Its index keeps two files of one path, as a diff across a rename can hold, two items.
        <CommandItem value={`${file.path}\n${file.index}`} onSelect={onSelect} className="font-mono text-xs">
            <span className="flex size-4 items-center justify-center">
                {file.viewed && <Check aria-hidden className="size-4 text-muted-foreground" />}
            </span>
            {file.viewed && <span className="sr-only">viewed: </span>}
            <span className="flex min-w-0 flex-1">
                <span className="truncate text-muted-foreground">{file.path.slice(0, slash)}</span>
                <span className="shrink-0">{file.path.slice(slash)}</span>
            </span>
            {file.cards > 0 && (
                <span className="shrink-0 text-muted-foreground">
                    {file.cards} {file.cards === 1 ? cards[0] : cards[1]}
                </span>
            )}
            <span className="w-20 shrink-0 text-right readout whitespace-nowrap">
                <span className="text-diff-add">{plus}</span> <span className="text-diff-del">{minus}</span>
            </span>
        </CommandItem>
    )
}

/** How an item ranks for what is typed in the field: 1 when its path holds it, else 0, which hides it. */
function holds(value: string, search: string): number {
    // An item's value is its path, then its index on a line of its own, which is not what is searched.
    const path = value.split('\n')[0] ?? ''
    return path.toLowerCase().includes(search.trim().toLowerCase()) ? 1 : 0
}
