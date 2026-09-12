# 0009. Join the team monorepo via `git subtree`, preserving history

**Status:** Accepted

## Context

The platform had been developed in its own standalone git repository. The team's actual shared
repository (`fire-incident-copilot`, containing `agent-service/`, `dashboard/`, etc.) needed our
backend as a `platform/` subdirectory. The team's shared repo turned out to have a somewhat
unusual branch situation: the branch our platform folder was first merged onto
(`feat/agent-service`) had **no common ancestor** with the team's real integration branch
(`main`), because `main` had since been reorganized/recreated independently.

## Decision

- Use `git subtree add --prefix=platform <our-repo> master` to import the platform repo's full
  commit history into a `platform/` subdirectory, rather than a plain squashed copy — so the
  history stayed inspectable in the combined repo.
- When the divergent-history problem was discovered (`git diff main...feat/platform` failed with
  "no merge base"), **rebuilt the branch from `origin/main`** instead of the stale
  `feat/agent-service`, re-ran the subtree add there, verified the diff was clean (pure additions,
  nothing in `agent-service/`/`dashboard/`/`data/`/`output/` touched), and force-pushed the
  corrected branch before opening the PR.
- Every subsequent platform update went out as its own small PR into `main` (never a direct push
  to `main`), each independently reviewed and merged by the user.

## Consequences

- GitHub's PR merges were **squash merges**, which flattened the subtree's split-point metadata —
  `git subtree pull` stopped working for *later* syncs ("refusing to merge unrelated histories").
  Follow-up small changes were instead synced by directly copying the changed files into the
  clone's `platform/` subdirectory and committing normally — simpler and equally correct for
  small deltas, at the cost of not being a "real" subtree sync anymore.
- Force-pushing the corrected branch was flagged and executed carefully: the environment's safety
  classifier blocked the automated force-push outright, so the user ran it directly rather than
  the assistant finding a workaround — the right outcome for a history-rewriting operation on a
  branch already visible to the team.
- The team's monorepo now cleanly contains `platform/` with intact internal history up to the
  first merge, alongside the other teams' folders, none of which were ever modified by this work.
