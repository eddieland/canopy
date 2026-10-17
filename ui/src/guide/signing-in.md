# Signing in

The web UI holds the operator's session, so it asks for the listener secret before it shows anything. Here is where
the secret comes from, and how a session ends.

## The listener secret

`canopy secret` writes it, to `listener-secret` in the user config directory (`~/.config/canopy/`), and prints it. It
never replaces one already there. Without one, `canopy loop` serves nothing and says how to make one; the loop goes on.

Paste it into the sign-in page once. The page sends it to the server and never keeps it, and a password manager can
file it under canopy.

## A session

A right secret signs the browser in for 30 days, through a cookie the page cannot read. The server keeps no session of
its own, so a session outlives a restart of the loop.

- To sign this browser out, use **Sign out** on [Settings](/settings).
- To sign every browser out, run `canopy secret --rotate` and restart the loop: a new secret ends every session.

A wrong secret is answered after a second, and logged.
