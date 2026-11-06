import { useState } from 'react'

import { PickerButton, PickerItem, PickerList } from '@/components/picker'
import { CommandSeparator } from '@/components/ui/command'
import { Popover } from '@/components/ui/popover'
import { reposSummary } from '@/lib/repo-filter'

// The item that stands for every repository: words no repository's name has, since a name holds no space.
const EVERY = 'every repository'
// What a repository picker's field and list are named, and what it says when what is typed leaves none.
const REPOSITORIES = { find: 'Find a repository', label: 'Repositories', empty: 'no repository has that name' }

/**
 * A filter by repository, for a workspace of any size (DESIGN.md, the repository picker): a button saying what is
 * chosen (`reposSummary`), opening `repos` in a list a field narrows, each checked while chosen, under
 * `every repository`, which clears them. Picking one adds or takes it away and keeps the list open, so several are
 * chosen in one go; Escape or a click outside closes it. What was chosen as it opened is listed first, so a long list
 * keeps it in reach, and no item moves under the pointer while it is open.
 */
export function RepoFilter({
    repos,
    chosen,
    onChoose,
    label = 'Filter by repository',
}: {
    /** The repositories to offer, sorted; those chosen among them. */
    repos: readonly string[]
    /** The repositories chosen, sorted; none filters nothing. */
    chosen: readonly string[]
    /** Hears the repositories chosen once one is picked. */
    onChoose: (chosen: string[]) => void
    /** What the choice is, for a screen reader, which hears it and then what is chosen: a filter's, unless given. */
    label?: string
}) {
    const summary = reposSummary(chosen)
    return (
        <Several
            repos={repos}
            chosen={chosen}
            onChoose={onChoose}
            label={`${label}: ${summary}`}
            summary={summary}
            every
        />
    )
}

/**
 * Several repositories of `repos`, in a form (an epic's): the same button and list as `RepoFilter`, without `every
 * repository`, since the form sends the names chosen and none means none. The button says `none` while none is.
 */
export function ReposChoice({
    repos,
    chosen,
    onChoose,
    label,
    none,
}: {
    /** The repositories to offer, sorted. */
    repos: readonly string[]
    /** The repositories chosen, sorted. */
    chosen: readonly string[]
    /** Hears the repositories chosen once one is picked. */
    onChoose: (chosen: string[]) => void
    /** What the choice is, for a screen reader, which hears the button as it and then what is chosen. */
    label: string
    /** What the button says, muted, while none is chosen. */
    none: string
}) {
    const summary = chosen.length === 0 ? none : reposSummary(chosen)
    return (
        <Several repos={repos} chosen={chosen} onChoose={onChoose} label={`${label}: ${summary}`} summary={summary} />
    )
}

/**
 * One repository of `choices`, in a form: the same button and list as `RepoFilter`, `null` among the choices standing
 * for every repository. Picking one sets it and closes the list.
 */
export function RepoSelect({
    choices,
    value,
    onValue,
    label,
    none,
}: {
    /** The repositories to offer, in order, `null` for every one. */
    choices: readonly (string | null)[]
    /** The one chosen, `null` for every repository. */
    value: string | null
    /** Hears the one picked. */
    onValue: (repo: string | null) => void
    /** What the choice is, for a screen reader, which hears the button as it and then what is chosen. */
    label: string
    /** What the button says while `value` is `null`, when `null` is not among the choices: nothing is chosen yet. */
    none?: string
}) {
    const [open, setOpen] = useState(false)
    const summary = value ?? none ?? EVERY
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PickerButton label={`${label}: ${summary}`} quiet={false}>
                {summary}
            </PickerButton>
            <PickerList {...REPOSITORIES}>
                {choices.map((name) => (
                    <PickerItem
                        key={name ?? EVERY}
                        value={name ?? EVERY}
                        checked={name === value}
                        onSelect={() => {
                            onValue(name)
                            setOpen(false)
                        }}
                    >
                        {name ?? EVERY}
                    </PickerItem>
                ))}
            </PickerList>
        </Popover>
    )
}

// A picker of several repositories: picking one adds or takes it away and keeps the list open, and what was chosen as
// it opened is listed first, so nothing moves under the pointer. With `every`, `every repository` heads the list and
// clears the choice.
function Several({
    repos,
    chosen,
    onChoose,
    label,
    summary,
    every = false,
}: {
    repos: readonly string[]
    chosen: readonly string[]
    onChoose: (chosen: string[]) => void
    label: string
    summary: string
    every?: boolean
}) {
    const [open, setOpen] = useState(false)
    const [first, setFirst] = useState<readonly string[]>([])
    const rest = repos.filter((r) => !first.includes(r))

    function toggle(repo: string) {
        onChoose(chosen.includes(repo) ? chosen.filter((r) => r !== repo) : [...chosen, repo].toSorted())
    }

    return (
        <Popover
            open={open}
            onOpenChange={(next) => {
                if (next) {
                    setFirst(chosen.filter((r) => repos.includes(r)))
                }
                setOpen(next)
            }}
        >
            <PickerButton label={label} quiet={chosen.length === 0}>
                {summary}
            </PickerButton>
            <PickerList {...REPOSITORIES}>
                {every && (
                    <>
                        <PickerItem value={EVERY} checked={chosen.length === 0} onSelect={() => onChoose([])}>
                            {EVERY}
                        </PickerItem>
                        <CommandSeparator />
                    </>
                )}
                {first.map((r) => (
                    <PickerItem key={r} value={r} checked={chosen.includes(r)} onSelect={() => toggle(r)}>
                        {r}
                    </PickerItem>
                ))}
                {first.length > 0 && rest.length > 0 && <CommandSeparator />}
                {rest.map((r) => (
                    <PickerItem key={r} value={r} checked={chosen.includes(r)} onSelect={() => toggle(r)}>
                        {r}
                    </PickerItem>
                ))}
            </PickerList>
        </Popover>
    )
}
