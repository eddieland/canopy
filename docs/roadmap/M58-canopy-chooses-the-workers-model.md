# M58. canopy chooses each agent's model

REQUIREMENTS R23, DESIGN §13 (Each agent's model), §8, §11, §12, §14, §21, §22, and §25, TRUST_MODEL T1, T5, T7, and T8,
D026, D040. Each agent's model, and its variant, is the operator's: a default per agent in `[runtime.models]`, a chore's
own `model`, and a ticket's override from `canopy model` or the ticket's page, rendered into the agent's definition,
with a template's `--model` or `--variant` a config error; every run the loop starts, and a tick's overseer, checks its
model against the runtime's list first and refuses `model_missing` or `model_list_failed` rather than fall back; each
run records the model asked for and, from its session, the models that served it, which `canopy spend`,
`canopy status`, the web UI, and a worker's commit trailer name.

Status: done 2026-10-29.
Learned: closed on the operator's real use, before a model dropped after it was set had been seen to refuse a
dispatch; that check is SCENARIOS S69. OpenCode's source changed the plan three times: a template's `--model` beats
the definition's, no `--format json` event names the model that served, so it is read from `opencode export` after the
run, and an unlisted model is refused before the first call while an unlisted variant is dropped without a word, which
canopy's check now catches. OpenCode 2.1.2 ignores a definition's model; 2.1.4 honors it.
