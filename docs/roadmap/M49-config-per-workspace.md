# M49. Config per workspace

REQUIREMENTS R19, DESIGN §12 and §18, TRUST_MODEL T7, D016, D053, D066. Each workspace has a private file,
`.canopy/config.toml`, layered last over the workspace file and the user file; private keys may be set only there or in
the user file, `canopy init` writes it, and the user file is optional.

Status: done 2026-10-17.
Learned: closed by the operator with half the live check run. The toy workspace (TOY_REPOS), a second workspace beside
the operator's, read its own queue label and `serve.port` from its private file, and its loop served on that port. The
operator's move of their own workspace's keys into its private file was not run; they accepted that it may break their
user file as it stands.
