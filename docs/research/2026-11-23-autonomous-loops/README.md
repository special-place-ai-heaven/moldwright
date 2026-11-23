# Autonomous agent loops: the claudefa.st vision against the moldwright factory (2026-11-23)

Sources read with crawl4ai:
- [Autonomous agent loops](https://claudefa.st/blog/guide/mechanics/autonomous-agent-loops)
- [Ralph Wiggum technique](https://claudefa.st/blog/guide/mechanics/ralph-wiggum-technique)
- [Thread-based engineering](https://claudefa.st/blog/guide/mechanics/thread-based-engineering)
- [Feedback loops](https://claudefa.st/blog/guide/development/feedback-loops)
- [Async workflows](https://claudefa.st/blog/guide/agents/async-workflows)
- [Custom agents](https://claudefa.st/blog/guide/agents/custom-agents)

Code read with SymForge on `dev` at `3d172845`:
- the live dispatcher: `tools/factory/dispatch.py`, `states.py`, `dispatch.json`, `control-bounds.json`;
- its stations: `proof.py`, `acceptance.py`, `planning.py`, `causes.py`, `resolver.py`, `tiers.py`, `learn.py`, `escapes.py`, `renewal.py`;
- the CI check `.github/workflows/red-green.yml` and `redgreen.py`;
- the engine's stop hook, `apps/engine/src/agents/claude-goal-hook.ts`.

## The articles' model in one paragraph

Work is a spec ("the pin"), then tests written first, then an agent loop that a stop hook will not let end until the tests pass (with a completion promise and a maximum number of iterations). Progress is saved outside the context so a restart resumes. Work scales as "threads":
- **P:** parallel, isolated in worktrees.
- **C:** chained, with a check between phases.
- **F:** fusion, best of N.
- **B:** an orchestrator with workers.
- **L:** long-running.
- **Z:** zero-touch. The agent ships behind feature flags, watches analytics, decides whether the change worked and iterates.

Screenshot review is "the missing piece" for UI. Cost is quoted per hour.

## Already met

| Article mechanism | Moldwright equivalent |
|---|---|
| Spec as the pin, with scope, out of scope and acceptance criteria | Issue headings `Change`, `Files`, `Done-test`, `Run`, `Test through`. The plan (`PLAN_BRIEF` in `planning.py`) numbers every ask, and each ask stands in exactly one slice or under `### Out of scope`, otherwise it is a plan fault |
| Two-phase workflow: plan, then build in a fresh context | Separate stations: Boss plans, Scope Shaper and IKE cut, and every build, review, fix and proof is a fresh run with its own brief (`dispatch.py`) |
| Stop hook, completion promise, maximum iterations | `goalStopHook` in the engine blocks a coworker's stop until its goal form is met (`PR:`, `PUSHED:`, `VERDICT:`, `PROOF:`, `BLOCKED:`, from `states.GOALS`), up to `turnLimit`, and records every verdict |
| Bounds on spinning | `clocks`: a run stops at 45 min, after 20 min with no progress, or at 3M tokens. Checks time out after 1 h; fast-check fixes, repair and recheck tries are capped at 2; the senior round is the last; the end state is `unsolvable` |
| Checkpoint state that survives a restart | The SQLite ledger with every state transition, atomic writes and recovery of a send after a crash (#1709). A returned job reopens in a new worktree (`a<take>`) and never on top of the old one |
| Parallel threads isolated by worktree | 15 slots, copies per coworker, limits on work in progress per state (`control-bounds.json`), `one_file_one_job`, one leased clone or worktree per job (`clones.py`) |
| Orchestrator with workers, chained phases | The dispatcher drives children of a parent issue; slices declare what they wait for; `acceptance.py` closes the parent once its children are merged |
| A separate agent verifies the work | A reviewer coworker distinct from the builder, then a read-only prover that judges every ask against the head commit |
| Model and effort per agent | `tiers` and `tier_models`: a model and a thinking level per station and per job size; readers run on Haiku, judgment on Sonnet |
| Economics | Tokens by kind for every run (`learn.record`), `job-cost`, and pacing against the weekly allowance (`renewal.plan`; stop at `plan_week_hold_percent` 95) |

## Where moldwright is already stronger than the articles

1. **"Red before green" is proven, not requested.** The articles ask the agent to write tests first. The CI check "Done-test red before green" (`redgreen.prove`) restores dev's code with only the PR's test files on top and requires the done-test to fail there and pass at the head. A test that passes on dev is rejected, and so is a PR that changes only tests.
2. **Done is judged against the exact commit, ask by ask.** The articles' stop hook trusts a word ("complete"). `proof.judge` requires `PROOF: PASS @<sha>` naming the current head and one `ASK n: MET|NOT MET` line for every ask, each with evidence. A stale commit, a missing ask or a PASS with an unmet ask is not a pass. `ASK n: NOT MET (plan)` sends the job back to the planner instead of the builder.
3. **Tests cannot be weakened to pass.** The CI checks "No stubs or switched-off tests" and "Refactor commits leave tests alone", and the prover's rule that an ask whose test was weakened is NOT MET, close the articles' failure mode "verification passes but work is wrong" by mechanism.
4. **A model-tier ladder and a senior round.** Instead of looping the same model up to 25 times, work goes up a tier by size, and a job that failed twice gets one last round on the senior model with every station's findings. A tier floor (`yield` 0.7 over at least 5 merges) keeps a cheap tier only while it delivers.
5. **Changes to the factory are measured, kept or reverted.** `causes.measure` compares the rate before and after each change to instructions or code, and files a revert issue by itself when the change made things worse. The articles have no improvement loop at all.
6. **The factory heals itself.** `resolver.py` detects whole-line problems (dev red, an idle line, a repeating error, a dead run, a failed checkout, no room), runs a high-tier model to resolve them, verifies the fix, and labels the issue for the owner only when it cannot.
7. **Facts are rechecked before a build.** `drift.py` rechecks a queued job whose facts dev has since changed.
8. **Defects after a merge count against the job.** `escapes.find` links reopened issues, repair issues and problems to the merged job within a window.
9. **Cost is measured as tokens by kind and share of the weekly allowance.** The articles quote dollars per hour. Moldwright measures cost per merged job, which is what "how much reliable work can you define" actually depends on.

## Gaps against the vision (ranked)

| # | Gap | Evidence | Smallest step |
|---|---|---|---|
| 1 | **UI is never seen inside the loop.** No build, proof or acceptance brief captures or inspects the rendered screen. The articles call this "the missing piece", and the project's own rule ("Verify in the app before calling it done", `pnpm verify:ui`) applies only to people and sessions | no screenshot, browser or `verify:ui` use in `acceptance.py`, `proof.py` or the build brief; the only "screenshot" in `tools/factory` is the plan brief's wording | For jobs whose files match `UI_PATH`, the acceptance or proof station runs `pnpm verify:ui` (or a `.context/verify/` scenario) on the PR's preview and reads the captures; an ask about the screen is MET only with a capture |
| 2 | **The plan review panel does not act.** Three critics (failure, structure, goal) exist but run in `mode: "dry"`: they write notes and nothing goes back | `dispatch.json` `planning.review.mode` | Grade the dry notes already collected, then switch to live for the lenses whose notes held up |
| 3 | **No best-of-N or tournament.** Every stage is one candidate; a hard failure moves up a tier but never tries several approaches side by side | nothing in `tools/factory` generates or compares candidates | For a plan marked large, or a job that reached the senior round, run two or three plans or fixes in parallel and let the judge station pick by the asks |
| 4 | **No arbiter for disputes.** Split reviewers, a third rejection or a builder contesting a review end as `unsolvable` or wait for the owner label; the arbiter loop in `LOOPS.md` (loop 17) is not built in the live path | `limits.after_reject` is used only by the idle runner; `dispatch.py` has no ruling stage | One ruling run at the highest tier that sees the plan, the diff and both positions, writes the ruling on the issue, and feeds later packets as a precedent |
| 5 | **No zero-touch tail.** Nothing deploys, flags, observes production or rolls back; the factory ends at merge | deploy by hand (`deploy/vps/update.sh`); no feature-flag system in `apps/ui`; `escapes` watches GitHub only | Deliberately out of reach today: deploys are owner-only by rule. Ready-made pieces when that changes: a deliver loop with snapshot and automatic rollback, flags for risky changes, and production error and usage signals fed into `escapes` |
| 6 | **No "until nothing new" stop for open-ended work** (audits, research, cleanup). Bounds are counts and clocks, not "no new findings in K rounds" | no convergence rule in the stations | A recheck station mode that stops after K rounds with no new finding |
| 7 | **Thread measures are partial.** Tokens, time and rounds are recorded; human interventions per job and the number of jobs in flight are not reported as trends | `digest`, `learn.record` | Add "owner touches per merged job" and "jobs in flight" to the digest; this is the articles' "fewer checkpoints" measure |

## Notes on code with no caller found

`stall_alarm.py` and `evidence.py` have no non-test caller in the repository, and nothing in `deploy/` or `tools/factory/triggers` schedules them; `clocks.stall_s` now covers stalls in the dispatcher. (`measures.py` is used: `status_report.py` imports it, run by `deploy/vps/factory-status.sh`.) These are candidates to remove or wire up. `runner_loop.py` runs in its own container (`deploy/vps/factory-runner.yml`) beside `dispatch.py`; two runners is a duplication worth settling.
