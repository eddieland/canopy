# Signing in

The web UI acts with your authority, so it wants the listener secret before it shows you anything. This page covers
where that secret comes from, and how a session ends.

## The listener secret

`canopy secret` makes one, writes it to `listener-secret` in your user config directory (`~/.config/canopy/`), and
prints it. It never replaces a secret that's already there; it just prints that one again. So when you've lost it, and
you will, run `canopy secret`.

Without a secret, `canopy loop` serves nothing and tells you how to make one. The loop itself carries on regardless:
the web UI is a window onto the loop, not a load-bearing wall.

Paste the secret into the sign-in page once. The page sends it to the server and never keeps it. Your password manager
is welcome to file it under canopy; that's what it's for.

## A session

The right secret signs this browser in for 30 days, through a cookie the page itself can't read. The server keeps no
session state of its own, so your session survives a restart of the loop.

- To sign this browser out, use **Sign out** on [Settings](/settings).
- To sign every browser out, run `canopy secret --rotate` and restart the loop. A new secret ends every session at
  once: the turn-it-off-and-on-again of auth, and it works for the same reason.

Everything a signed-in browser does is written down in the journal: when, what it asked for, how the server answered,
and the address it came from, though never what it said or the cookie it said it with. If the
secret ever gets out, that's the list of what was done with it. Reads aren't kept; looking is free.

When a session ends while you're using the page, the next request finds it gone and the page turns into the sign-in
page. If that request was an action, the sign-in page says it wasn't sent, so sign in and send it again; a reply you
were writing is kept for you.

A wrong secret gets its answer after a one-second pause, and the attempt is logged. Guessing is allowed. It's just slow,
and someone is writing it down.
