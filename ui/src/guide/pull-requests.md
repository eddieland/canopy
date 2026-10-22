# Pull requests and reviews

Every PR canopy knows about, and canopy's own reviews of them. The reviews are yours alone: canopy posts nothing of
one on its own, so this is the only place, besides `canopy review show`, you'll read them. On a coworker's PR, a review
is also a draft of your own review, which reaches GitHub only when you publish it ([below](#publishing-your-review)).

## The pull requests page

[Pull requests](/pull-requests) lists the loop's own PRs, every PR canopy reviewed, and every PR you asked it to
review, most recent activity first. Each row shows where the PR stands (a run working it, or its latest review's
verdict), the PR as `org/repo#123`, its phase, its ticket and title, and how long since anything happened. A PR canopy
only reviews has no ticket, so it shows `none` there; hover it for why. The name opens canopy's page for the PR; the
small icon beside it opens the PR itself. A link into a PR, say to one review thread, gets the same name wherever
an agent's text mentions it: the name still opens the PR's page, and the icon takes you to that exact thread. The PR
column is only as wide as the longest name in the list, and in a narrow window the phase goes first, then the age, so
the title keeps the room.

On a PR the loop doesn't own, a chip after the verdict says where your own review of it stands: `draft` while it waits
on you, `staged` once it's a pending review on GitHub for you to submit, `unconfirmed` while canopy doesn't know whether
a publish posted, and `published` once it did ([Publishing your review](#publishing-your-review)). `staged` and
`unconfirmed` are amber, since each waits on you or on GitHub; the rest stay grey. Scan the column for amber and you
know which coworkers are still waiting on a review you think you sent.

The field over the list keeps the PRs whose name, ticket, or title holds every word you type, in any case, so `web#88`
or `debounce` finds the one you mean without scrolling. With PRs in more than one repository, a repository picker
sits beside it: check one or several, type a few letters to find one in a long list, and **every repository** clears
them. Both live in the URL, so a filtered list is a link you can keep.

The title is the PR's own, as the worker that opened it or canopy's last review of it read it, so it says what the PR
changes rather than what the ticket asked for. Until one is reported, a loop PR shows its ticket's title. Titles are
read when canopy looks at the PR, not live: rename one on GitHub and canopy catches up at its next run or review.

A PR's page opens with where the PR stands, in the line under its title: canopy's latest review and its verdict, such
as `review:4 3 findings, 1 major` (or `not reviewed`), `at its review limit` once it is, and the run working it now.
A PR canopy only reviews says so there too. Below that, it gathers what canopy knows of the PR: its ticket and branch,
or, on a PR the loop doesn't own, **your review**, where your draft stands with a link to the review that holds it,
what it has cost, its coworkers' review threads when canopy has read them (below), canopy's reviews of it, the runs
that pushed to it, and the decisions that named it. A list with nothing in it shows its header and a `0`, and nothing
else: an empty list doesn't need a paragraph. A PR with no ticket has no Runs at all, since runs belong to a ticket.
When a PR has used every review it's allowed, its page shows **At its limit**, with **Allow one more**, and under
it the same as a command, `canopy grant URL review`. The limit is `policy.max_reviews_per_pr`, three by default; a
grant works as a ticket's does ([Allowing one more run](tickets#allowing-one-more-run)).

## Replying to your coworkers' reviews

When a coworker reviews one of the loop's PRs, the worker that answers them doesn't post its replies. It drafts them,
and you send the ones worth sending, as your own words. That's `trust.review_replies = "approve"`, the default. Set it
to `"post"` in your own config and workers post their replies themselves, each starting with `CANOPY:` so nobody
mistakes them for you.

The PR's page shows its review threads on the diff the latest run pushed, each at its line, with the run's draft under
the thread it answers. canopy reads the threads itself, so what you see is what GitHub holds, not the worker's
recollection of it. The line over them says which mode `trust.review_replies` is in, and when canopy last read the
threads and at which commit, or that it hasn't yet. A thread on a line that's since changed sits under its file, marked
`outdated`. If the PR has moved on past the diff the page shows, a warning above the diff says so. Its files fold and
filter by type as a review's do ([below](#a-reviews-page)).

Not everything has a line to sit on. A thread on a file the diff doesn't show waits in **Not in the diff**, after the
files; when no run kept a diff at all, every thread is listed whole under **Threads**. A draft for the review's own
text, rather than a reply, sits in **The review's body**, and one no read of the PR has placed on a thread yet, or
that named a thread the PR doesn't have, in **Not on a thread**, so a draft never goes missing for want of a place to
put it.

Comments show as plain text, never Markdown, with any character that hides text named by its code point. The one
exception is a `<details>` block, which folds under its summary line as it does on GitHub, so a review bot's prompt for
agents stays out of your way until you open it. A closed block that hides a character says so on its line: a fold is
where you'd tuck something you hoped nobody would read.

The panel at the top lists every draft on the PR, in the order the page shows them: where it stands, its run, its
first line, and where it sits, such as `src/search/useSearch.ts:16`. The first line links to the draft's card, opening
its file if you'd folded it away, so a PR with forty threads doesn't turn into a scrolling contest.

Each waiting draft has three buttons:

- **Send** posts it, word for word, under your name, with no mark: you approved it, so it's yours. It's
  `canopy draft send`.
- **Edit** opens the text to rewrite, up to 4,000 characters, counted as you type. **Save**, or the send key
  you chose in [Settings](settings#replies), keeps your version beside the run's, and **Send** then posts yours.
  **Cancel** leaves the run's as it was.
- **Drop** means nobody sends it. **Undo** takes that back.

A reply on a thread can carry a reaction too, a 👍 or any of the eight GitHub offers, put on the comment it answers. A
worker may propose one, and sometimes nothing else: a thumbs up on a nit it fixed says "Done." without the comment.
The card shows the reaction under the text. **Edit** has a row of them to pick from; pick the lit one again to take
it off. To send the reaction alone, leave the text empty: once a reaction is picked, **Clear text** beside it empties
it in one click, which beats holding backspace through a worker's earnest paragraph for a review bot that won't read
it. A send adds the reactions first, then the review. GitHub keeps one of each per person, so if the review then
fails, the reaction stays, the card says so, and sending again won't stack a second 👍 on your coworker's comment.

**Send N waiting**, at the top, sends every waiting draft together. Either way, one PR's drafts go as one comment
review, so your coworker gets one notification rather than a burst. The button reads **Sending…** while the post is on
its way, and once it lands a toast at the bottom of the window says what went and where it went, so you're not
left wondering whether that click took. If anything didn't make it, the toast wears a cross and the line under the card
says why. canopy never approves, requests changes, or
resolves a thread: whether the conversation is over stays the reviewer's call.

**Start a review on GitHub**, beside it, puts the same waiting drafts in a pending review on the PR instead, the replies
on their threads and the review's body as its own, and stops there. Only you can see it. Open it on GitHub, add your own
comments, reword what you like, and submit it yourself: it's `canopy draft stage`, for when you'd rather your last click
be on GitHub. GitHub has no such thing as a pending reaction, so a draft's 👍 goes on its comment the moment you click,
and a draft that's only a reaction is simply sent; the help line warns you first, and the toast counts them after. The
staged cards say where they are, and the panel links to the PR's files, where GitHub keeps its **Finish your review**
button. canopy's next read of the PR settles them: sent once you submit, dropped if you took a reply out first, waiting
again if you deleted the review. Until then nothing else is sent on that PR, because GitHub gives each person one
pending review per PR and canopy isn't about to delete yours.

canopy is careful about what it posts. A send carries the hash of the text you saw, so if the draft changed in another
tab, it's refused `stale` rather than sending words you never read. If a coworker commented on the thread since the
run, the send is refused `thread_changed` and the page shows the new comment: read it, then send again if your reply
still holds. A newer run's draft for the same thread replaces an unsent one, and if you'd edited the old one, the new
card warns you that your edits didn't come along. A draft is never posted twice; one whose post ended without saying
whether it worked reads `unconfirmed` until canopy's next read of the PR settles it.

The [attention list](attention) holds a `drafts waiting` item while any draft for the PR waits on you.

## When canopy reviews

A review is a fresh agent's adversarial read of one PR at one commit: it's told to assume the change is wrong and go
looking. canopy reviews:

- **The loop's own PRs**, with `review.agent_prs` set: once checks pass, before a human is asked. Each new commit is
  reviewed again, up to the limit. What happens to the findings depends on whether you trust the reviewer, below.
  With `[personas] reviewers` in your config, each commit gets one review in every persona it names instead of one
  ([Choosing a persona](tickets#choosing-a-persona)). Each counts against the limit, so three personas against the
  default limit of three spend it on the first commit.
- **PRs matching your query**, `review.query`, such as your team's: reviewed and nothing more. The loop never
  pushes to them, fixes them, or opens a ticket for them.
- **A PR you ask about**, below.

It reports defects the change brings, not style and not what CI already checks. Each finding says what's wrong, the
case that shows it, and the smallest fix, pinned to the line of the diff where it lives. A bug the code had before the
PR goes in the summary instead, so a worker is never sent to fix code its PR didn't touch, which is how a two-line fix
becomes a refactor nobody asked for.

Reviews are off while `capacity.max_reviews` is 0, and each commit is reviewed once in each persona chosen for it.

A review of a new commit isn't starting from scratch: it reads canopy's last finished review of the PR, the summary
and every finding you didn't dismiss, and checks whether each still holds. A finding the worker fixed stops coming back,
and one it didn't is reported again. It still reads the whole change, though. Being told where the last reviewer
looked is useful; being told where not to look is how a bug lives through three reviews.

The reviewer runs its own command, `runtime.review_cmd`, so point it at another model than your workers': a second
model misses different things than the first, which is the point of asking it. canopy sends the reviewer no temperature
(`runtime.review_temperature = -1`, the default), because OpenAI's reasoning models refuse a request that sets one, and
a review that never starts finds nothing. If your reviewer's model takes one, set it low, such as `0.1`. Each new commit
is reviewed again, and a reviewer sampling hot finds something fresh every time in code nobody touched; with the
reviewer trusted, each of those sends a worker back. A cool one says much the same thing twice, which is also how
you'll learn whether it deserves that trust.

canopy treats its own reviewer as it treats anyone else's. With `canopy:review` in `trust.trusted_reviewers`, findings
on a loop PR send a worker back to address them, and the PR's phase is `review findings`. Without it, the findings wait
as `untrusted review` on your attention list until you say which to act on. Untrusted is the default, and a sound
one: the reviewer is wrong often enough that you'll want to read a few before it spends runs on its own say-so.

## Asking for a review

To have canopy review a PR the loop doesn't own, such as a coworker's, paste its URL into **Review a PR** on the
[reviews page](#the-reviews-page) and press **Review**. This is `canopy start URL --review`. A link to one of its
threads or its files tab works too: the page trims it back to the PR, so you needn't. The page then opens the PR's
own page, where the request now stands. The next tick reviews the PR once, at its latest commit, in whichever of your
repositories holds it, and the request ends with that review. Until then it's a `requested` row at the head of the
reviews list, so you can see it landed, and it waits on the [pull requests page](#the-pull-requests-page) wearing
`requested` too. The PR's page shows the open request, with **Stop** to withdraw it, and says where it came from, `web`
or `cli`. Once the request ends, the page says when and why: `reviewed`, `stopped`, `merged` or `closed` before a
review got to it, or `unknown_repo` when none of your repositories holds the PR.

Already on the PR's page? Its **Pull request** panel asks for you: **Review this PR** on one canopy has never
reviewed, and **Review again** once it has, or once your request has ended, say after the author pushed a fix. It's the
same request, in the personas its menu names: the last request's, or those [Settings](settings#reviews) prefers. The
loop's own PRs have neither button. `review.agent_prs` reviews those, and canopy would refuse the request anyway.

**Show persona and notes**, under the URL, opens the rest of the form. **Notes for the reviewer** takes whatever you
want the reviewer to know before it starts: what the author asked you to look at, the part of the change that worries
you, or why the PR exists at all. It's optional, and it's `--notes` on the command line. The reviewer weighs your
notes ahead of the overseer's pointers, but they don't narrow the review: it still reads the whole change. The PR's
page shows the notes with the request. Asking again for a PR that's already waiting, with new notes, replaces the old
ones; a review already running keeps the notes it started with.

**Persona** picks the voice the review is written in, as `--persona` does. Left alone, it reads `(default)` beside
`[personas] reviewer`'s, which is usually `canopy`; folded, the form says which it will use. Each persona in the menu
says what it is under its name, in its own words. Check one persona, say `skeptic`, and the review is
written in it; check several, up to ten, and canopy reviews the PR once in each, side by side, which is the cheapest
way to learn which reviewer you actually like. Each is a run of its own, billed as one. A persona canopy would refuse
to run, such as a file past its size limit, is greyed out, and hovering it says why. Asking again for a PR that's
waiting, with personas checked, replaces its personas; with none checked, it keeps them. The PR's page names the
personas with the request.

If you always reach for the same reviewer, pick it once in [Settings](settings#reviews) and the form starts there,
saying `as Settings prefers`, and so does a PR's **Review this PR**. You can still check others for one request; the
next one starts from your preference again. **Use the default** is still `[personas] reviewer`'s.

The review stays in canopy until you say otherwise. Its page holds it as a draft of your review on the PR, which you
can trim, reword, and publish ([below](#publishing-your-review)); whether you pass any of it on, and in what tone, is
between you and your coworker.

## The reviews page

[Reviews](/reviews) lists every review, newest first: its verdict, its ticket, how big the change is (`low impact`,
`normal impact`, `high impact`), the PR and commit, the persona it wrote in (`as skeptic`, where the list has room for
it), and what it cost. A PR you had reviewed in several personas gets a row for each, and the persona is how you tell
the skeptic from the minimalist. The reviews one request made of one commit sit together, with no rule between them:
the first names the PR, and each after it says only `as minimalist`, since the PR and commit are the first's. The
PR's page lists them the same way. A verdict reads `clean`, or counts the findings with the worst among them, such as
`3 findings, 1 major`. A finding is `blocking`, `major`, or `minor`. A review of a PR the loop doesn't own carries its
draft's chip after the verdict, as the pull requests list does. With no review yet, it points you to **Review a
PR** above the list, which works with the defaults, and to `review.agent_prs` and `review.query`, which have the loop
review PRs on its own. Either way, `capacity.max_reviews` must be above 0.

A PR you asked for that no review has started on yet leads the list as `requested`, with a hollow ring: it has no
verdict, commit, or cost because nothing has read it yet. Where a ticket would be, it names the PR's author once canopy
has read the PR, which it does at the next tick; until then it says `none`. Once a tick starts its review, the review's
own row takes its place. If that review fails, the request is still open, so the `requested` row comes back and the
next tick tries again.

The reviews list filters as the PRs do: a field for words in the PR, its ticket, or the commit (the first few characters
of a sha will do), and the same repository picker. A `requested` row drops out once you pick a repository, because
which one holds its PR is the next tick's to work out, not the page's to guess.

A review that has finished since you last looked is new, if it has something to say: one that found anything, or
any review you requested, clean or not. A clean review the loop started on its own stays quiet; it is in the list,
but nobody needs a notification that nothing is wrong. A new review's row has a dot after its verdict, and **Reviews**
in the side navigation counts the new ones on every page, in the color of the worst finding among them, so a blocking
one stands out from a clean one you asked for. Opening a review's page marks it seen; **mark 3 seen** in the list's
header does it for all of them at once, for the days you trust the summary. canopy keeps what you've seen in its
journal, so your laptop, your desktop, and the terminal agree: `canopy review show` ends a new review's line with
`new`, and `canopy review show ID` marks it seen as the page does. Only you can mark one: an agent that reads a review
in full leaves it new, which is the point of a list of things you haven't read.

## A review's page

At the top, the reviewer's summary, since that's the answer you came for, then its verdict with how big the change is,
the PR (with its other reviews, if any, on a line under it), the persona the reviewer wrote in, the commit it read and
the base branch it was read against, and when its run ended, with a link to the run. The persona carries the start of
its text's digest, whole on hover: two reviews in one persona with different digests had it edited between them. When
the harness decided the review's status itself, such as failing a run that never reported, its reason is the red
**harness** note under the summary. The status is the line under the title. Then its findings, each linking to where it
sits, and the diff, a panel per file, with each finding pinned under the line it names. A finding on a line the diff
doesn't show sits under its file's header, and one about a file the diff doesn't touch waits in a panel of its own after
the files. A long diff shows the lines around each finding at first, with folds that open the rest. A renamed file is
headed `old → new`, and a binary one is marked `binary`. A diff too long to keep whole says so at its end. A review that
holds a draft of yours leads with the draft instead, and folds all this but the diff under it
([Publishing your review](#publishing-your-review)).

An old review may have no diff kept, either from before canopy kept them or because your `[retention]` removed it with
the review's log, which the page says as `removed after 30 days`. Its findings list is then the cards themselves, each
with its location, its detail, and **dismiss**, so each finding is on the page once, which is about as often as you want
to read a blocking one.

**Hide diff**, on a file's header, folds that file away to one line saying how much it hid; **Show diff** brings it
back. To read only some kinds of file, open **All file types** above the first file and untick the rest: a lockfile's
thousand lines are rarely where the bug is. **Show every type** ticks them all again. Following a finding from the list
opens its file again, and ticks its type, so nothing you folded hides a finding from you.

The diff runs from where the PR's branch left the branch it merges into, so a PR stacked on another branch shows only
its own commits. If canopy had not read the PR from GitHub when its review started, the diff runs from the
repository's base branch instead, and a stacked PR shows its parent's commits too: if a finding seems to be about code
the PR never touched, check that first.

## A review's run

The results are the page you read; how the reviewer got there is a page of its own, one link away under **run**:
**transcript and log**. It's the review in the trail, then **Run**, and holds what [a run's page](runs#a-runs-page)
does, [Context](runs#context) included: what a failed review ended on, the harness's note, when it ran, what it spent
and on which model, and where its log is; then the reviewer's transcript, every file it read and command it ran, the
prompt canopy handed it, and the log's end as written, each folded until you open it.

Open it when a verdict surprises you, or when a review failed and you want to know whether to blame the reviewer, the
PR, or the runtime. A reviewer's events reach its log when it ends, so while it works the transcript says so and
waits; there is no watching it think.

## Acting on findings

A review changes nothing on its own: canopy never approves a PR, requests changes on it, or merges it. What you can do
is tell canopy which findings matter.

- **dismiss**, on a finding's card, as `canopy dismiss review:ID N`: no worker or tick acts on it. It stays listed, and
  **undo** brings it back. If you dismiss every finding, the PR moves on as if the review were clean.
- **send to a worker**, on a finished review of one of the loop's own PRs: tick the findings worth fixing and press
  it, as `canopy send review:ID N`. canopy records a reply on the ticket naming them, and the next tick reads it as
  your go-ahead for a worker to fix those and leave the rest alone. For an untrusted reviewer it's the go-ahead the
  findings wait for; for a trusted one, it narrows what the worker takes on.

A review of a PR the loop doesn't own has no worker to send to; it has a draft instead (below). Dismissals and sends
belong to one review, so a new commit's review starts fresh.

## Publishing your review

A finished review of a PR the loop doesn't own, a coworker's you asked for or one `review.query` matched, is also the
first draft of a review you could leave on it, and its page is about that draft. The title says so, **Your review of
acme/api#14 by carol**, and the line under it says where the draft stands: waiting on you, staged on GitHub, published,
or unconfirmed while canopy finds out whether a publish landed. **Draft review** comes first and shows exactly what
canopy would post in your name: the reviewer's summary as the body, each finding on a line of the diff as a comment on
that line, and a finding the diff doesn't show tucked into the body under its location. On the diff, each finding is
one card: its severity and title from the reviewer, then the comment as it will post, marked **in your review** or
**left out**. Every word is the reviewer's, written after reading the PR, so read it as you'd read
anything a stranger wrote about your coworker's code before signing it: hidden characters are named, never hidden.
Hover the version in its header to see who made it and the hash a publish carries.

A request in several personas made a review, and so a draft, in each. The draft says so under its intro, **Also
reviewed as skeptic, minimalist**, each name opening that review's page, so you can read them side by side and publish
the one you'd sign. Publishing one leaves the others as they were: a draft you didn't pick is still a draft, not a
second review waiting to surprise your coworker. The attention list's `review waiting` clears once any of them is
published or staged.

canopy's own review, the summary, verdict, and findings list from [a review's page](#a-reviews-page), folds under the
draft as **What the reviewer found**, its status and verdict on the fold. **Show the review** opens it, for when you
want to check the draft against what the reviewer actually said.

Change it until it says what you would:

- **edit**, beside **Body**, rewrites the body; empty, the comments post alone.
- **Edit**, on a finding's card, rewords its comment in place.
- **leave out**, on the same card, takes the finding out of your review: it dismisses the finding, which drops its
  comment or its paragraph of the body. **put back** takes that back, in the reviewer's words, so your edit of it goes
  with the dismissal. The **Comments** list says which findings you've left out.
- The **+** beside a line's number on the diff, there when you hover the line, opens a comment of your own on it. Yours
  keep cards of their own, with **Edit** and **Drop**.

A finding can also leave your review without a dismissal: you rewrote the body it lived in, or dropped its comment with
`canopy review edit --drop`. Its card then says **left out** and offers **dismiss**; canopy only puts a finding back by
taking its dismissal back, so dismiss it, then **put back**. Two clicks, and the reviewer's words return.

Each change is a new version, listed under **Versions** with who made it, and is the same as `canopy review edit`.
A version holds at most 30 comments, which is more than any review worth reading needs.

Or have an agent do the rewording. Under **Revision**, say what should change in **What should change** and press
**Ask for a revision**, the same as `canopy reply review:ID`. The next tick starts a revision: an agent reads the PR and
the version on the page, with your note as its only instructions, and makes a new version, listed **by a revision**.
It posts nothing. Write the note as you'd brief a colleague who takes every word literally, because this one does.
Until then the panel shows your note and says a revision is asked for, then running; if you edit the draft first, your
version answers the note and no revision starts. A note is refused while a revision runs, and once the draft has had
its revisions (`policy.max_revisions_per_draft`, 3 by default), which `canopy grant review:ID revision` raises from
your shell. A revision that fails leaves the draft as it was, and the panel says how it ended. The page shows what a
revision did when you next read it; it doesn't follow the run as it goes, so reload to see the new version.

Two buttons sit at the foot, as they do under a PR's thread drafts. **Publish version N** posts the version on the page,
word for word, on the commit the review read, and submits it. **Start the review on GitHub**, beside it, posts the same
as a pending review instead: only you can see it until you submit it, or delete it, on GitHub, and canopy's next read
of the PR records which. The line beside them says exactly what goes out, the body and how many comments, on whose PR
and which commit, so there's no guessing what your name is about to be attached to. Either way it is one comment review
that approves nothing and requests no change, and it's `canopy review publish RUN HASH`, with `--submit` for the
first. A toast says what went and where; the panel keeps a line linking to it on GitHub, and a published one drops a
leaf, as an approved plan does. Staging gets none: nobody has seen it yet. The hash is the version you
looked at, so if anything changed it since, the publish is refused as `stale` and you read it again. A draft publishes
once; a later commit's review is a draft of its own. If the PR has moved on since, the panel says so: your comments
would land on the old commit and show as outdated.

The [attention list](attention) holds a `review waiting` item while a review you asked for has a draft you
haven't published or staged, and a `review unsettled` one while a staged review waits for you on GitHub, or a post
never said whether it landed. A review `review.query` found raises neither until you stage it.

canopy can't take a published review back, and nothing on GitHub says a model wrote it but what you leave in.
