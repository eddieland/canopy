When you review, name the input that breaks a claim before you accept it. For each thing the change says it does, ask
what value, order of events, or failure would make it false, and look for that case in the code and its tests. A claim
you tried to break and could not is accepted; one you did not try to break is not yet reviewed. Say in a sentence what
you tried, so the next reader knows what held.

When you plan, treat each step as a claim about the code: name the case that would make it wrong, such as an empty
input, a second caller at the same time, or a failure halfway through, and say how the plan meets it or that it is out
of scope. A plan whose riskiest step names no such case is not done. Be as long as the work needs and no longer.

Prefer a concrete counterexample to a general worry: "a key with a slash reaches the path unescaped", not "input
validation may be incomplete". When you cannot name one, say the doubt once and move on.

When you write anything else, such as a commit message or a reply, write plainly and briefly. When a PR already has a
body, edit it only if a sentence in it is wrong or missing, and change only that sentence.
