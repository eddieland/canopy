#!/bin/sh
# Vercel's ignored build step (vercel.json `ignoreCommand`): exit 0 skips the build, anything else builds.
#
# Skips when nothing changed since the last deploy but files the demo never serves. VERCEL_GIT_PREVIOUS_SHA is the
# last deployed commit, so commits pushed together count as one; without it, the parent. A commit missing from
# Vercel's shallow clone makes git fail with 128, which builds.
git diff --quiet "${VERCEL_GIT_PREVIOUS_SHA:-HEAD^}" HEAD -- . \
    ':!docs' ':!tests' ':!.github' ':!examples' ':(exclude,glob)*.md' ':!LICENSE'
