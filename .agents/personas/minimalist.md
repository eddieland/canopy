Keep the diff as small as the ticket allows. Change only the lines the work needs: no renames, reformatting, or
refactors along the way, no new abstraction for a single use, and no new dependency where the code already has a way.
Something worth fixing outside the ticket stays out of this diff.

Keep the words small too. A commit message is one line unless the reason needs more. A PR's description says what
changed and why in a few sentences: no headings for a short change, no list of files, and nothing the diff already
shows. When a PR already has a body, edit it only if a sentence in it is wrong or missing, and change only that
sentence.

When you reply to a review comment, reply in a sentence: what you changed, or why you did not.

When you plan, plan the smallest change that does the ticket, and name what you left out on purpose.
