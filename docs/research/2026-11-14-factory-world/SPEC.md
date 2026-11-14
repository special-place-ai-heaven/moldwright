# The factory world: design spec
as_of 2026-11-14. Status: DRAFT, the owner's direction written down before the build. Dark by default.
Supersedes `docs/research/2026-11-14-factory-view/DESIGN.md` except its section 5 (what the app can read).

The factory is a chip fab, not a board of cards. Owner: "Have you seen how silicon chip waffers are made and
chips are produced? Where they travel in these crate packets on lines", "silicon waffers are tasks, that get
transported to those cabinets and put in there like vinyl records".

Everything in it is a finite, known thing: a feature is cut into a known number of tasks, each task passes
known stages, so every count on the floor is exact and every motion says something true. Nothing moves for
decoration. Built in Rerun's own isometric engine (`packages/ui/src/iso-grid`), extended with new objects;
real WebGL (`THREE-D.md`) only if a slice there cannot carry glass and light convincingly.

## 1. Objects

| Object | What it is | How it looks |
|---|---|---|
| **Coworker = tool** | a Rerun coworker (`code`, LINUS, Boss...) | Rerun's rounded buddy with its face, 2x2, alive: bob, blink, squash. It is the tool a wafer is processed at. |
| **Copy** | one more run of the same coworker at once | the same buddy, glassy and see-through, budding out of its coworker and melting back |
| **Overhead rail** | the path work takes between coworkers | a rail of light joining coworkers (the fab's overhead transport); current runs along it both ways |
| **Pod** | the carrier a task rides in | a small glassy pod (the fab's wafer carrier) hanging from the rail, gliding between tools; it opens at a tool and closes to travel |
| **Wafer = task** | one job: an issue cut for the factory | a thin glowing disc inside the pod. Its surface is a grid of dies that light up as the task passes its steps, so its progress is counted, not guessed. |
| **Cabinet = feature** | the parent issue a task was cut from | a tall cabinet with one slot per task of the feature (the count is known from the cut). A finished wafer slides into its slot like a record into a sleeve; the cabinet is complete when every slot is filled. |
| **Foreman's post** | Boss, who plans and cuts | Boss's buddy on a raised post over the floor; talking to him opens his chat (Rerun's coworker chat) |
| **Delegator = loader** | the dispatcher that sends and merges | a machine at the head of the line: loads wafers into pods, sends them out, seals the merge |
| **Checks gate** | the workflow runs of a pull request | an arch over the rail with one light per check |
| **Gauges** | plan week, sign-in | physical: a reservoir that drains as the week is used, a lamp that dims as the sign-in ages |

## 2. What lights up, and from what

- **A wafer's dies** light by stage and by step. Stages from the ledger (`jobs.state`, `transitions`): queued,
  building, review, checks, merged. Inside a stage, steps of the run (`fires.steps`, the step count the
  delegator already reads) light dies in that stage's band, so a wafer in a long build visibly advances. A wafer
  is complete when its last die lights at the merge.
- **A cabinet** has one slot per task of its feature. Filled slots show how each task ended: a lit wafer
  (merged), a dark one (rejected), a cracked one (blocked, failed, returned). Empty slots are the exact work left.
- **Die colour** is the coworker type that lit it (build, review, checks), so a wafer is a record of who
  worked it.

## 3. Statuses and their tells

Every status has its own tell, by shape and motion as well as colour. "Ledger" says whether the delegator
records it today (`tools/factory/store.py` `JOB_STATES`, `holds.py`, `fires`).

| Status | Ledger | Tell |
|---|---|---|
| waiting on a task | `waiting` | pod parked on a siding, a thin light thread to the wafer it waits on |
| queued | `queued` | pod in line at the loader, steps forward as the line moves |
| held | yes (`holds.py`) | rails dim, pods stop where they are, a barrier of light drops at the head, a padlock on the loader |
| building | `building` | pod docked and open at a copy; the copy works over the wafer, dies light one by one |
| review wait | `review_wait` | pod queued in front of the reviewer, closed |
| reviewing | `reviewing` | reviewer's eyes scan; a sweep of light passes across the wafer |
| fix wait / fixing | `fix_wait`, `fixing` | pod rides the return rail; a scratch on the wafer glows and heals as the fix runs |
| checks | `checks` | under the gate; one light per check comes on in order |
| merged | `merged` | last die lights, the wafer shakes gently, the pod carries it to its cabinet, it slides into its slot |
| rejected | `rejected` | the wafer dims and goes into its slot dark |
| blocked | `blocked` | pod stops, one sharp shake, a diamond badge with the reason in a bubble; it stays until someone acts |
| failed / returned | `failed`, `returned` | a crack across the wafer, one shake; into its slot cracked |
| stalled | from `fires` (step count not moving past the clock) | the copy holding it slows and greys; a clock badge |
| over budget | from `fires` (tokens past the cap) | the wafer overheats, glowing red at the edge; the copy shudders |
| replaced | **needs dispatcher work** (no state) | the wafer dissolves into light that flows into its replacement |
| cancelled | **needs dispatcher work** (no state) | the pod lifts off the rail and fades |
| delegator not answering | heartbeat file | the whole floor dims, motion freezes, a clock shows the last beat |

**Feature link: needs dispatcher work.** The ledger has no task-to-feature link; the cut names its parent only
in prose ("Part of #198"). The cut format gets a `**Part of**: #n` line, read like `**Depends on**`, and the
ledger keeps it; until then a cabinet's slot count is not exact.

## 4. The motion language

Refined: data flows on rails both ways; each change of status has its own tell (start = a squash and a light,
finish = a pulse that settles, error = one shake, waiting on a person = a slow breath, hold = dim and lock);
small hints sit where the change happened; glows fade, never blink; idle things stay quietly alive.

Cheap, never: everything moving on one beat; spinners and loops that mean nothing; colour as the only
signal; shaking what is not wrong; pop-ins with no easing; piled bubbles; motion that fights a drag or a click;
layout jumping when data refreshes.

Timings and easings: MOTION.md (R1 hop, R2 landing, R3 copy ripple, R4 shadow, R7 handoff comet, R9 spring).
Pods ride the cable's own path (OPEN-SOURCE.md items 1 to 3: an upright parcel on `offset-path`, one id per
job so it travels instead of reappearing, a queue that backs up). Live data is played one beat behind and
smoothed (AI Town).

## 5. Around the floor (Rerun parts, repurposed)

- **Foreman chat:** Rerun's coworker chat (`components/chat/AgentChat.tsx`) for Boss, in the shell of the
  foreman column (`components/foreman/ForemanColumn.tsx`), restyled to the factory.
- **Bot panel:** clicking a coworker opens Rerun's side panel (`components/agent/AgentPanel.tsx`): chat, runs,
  schedules, model, effort, skills, tools, services.
- **KPIs:** Rerun's monitoring cards and charts (`packages/ui/src/monitoring`, `AgentPanelMonitoring.tsx`),
  summed across the factory's coworkers; per task: tokens, duration, fix rounds (`fires`).
- **Construction view:** the row of cabinets is the overview; a cabinet opens its wafers.
- **Settings:** Rerun's dialog pattern (`PanelEditorShell`, `Segmented`, `Switch`) over the delegator's
  settings: pools, runs per coworker, clocks, holds. Needs a read and write path to the delegator (gap).

## 6. Open

- The data path from the delegator's ledger to the app does not exist yet; every number waits on it.
- Pausing a coworker by hand does not exist in Rerun (gap found in the map of the app).
- Eyes that look around on a board: Rerun turns them off when many buddies share a board (`styles.css`,
  "twenty buddies glancing at once is noise"). Proposed: a per-task eye motion (scan while reviewing, look
  down while building) instead of free glancing. The owner decides.
