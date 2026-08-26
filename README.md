# Authoring tasks on your own codebase

This project collects realistic software-engineering tasks built on your private repositories: a precise behavioral instruction, your reference solution, and a held-out test suite that decides pass or fail objectively. Every submission runs a strict automated pipeline before human review. Approved tasks pay $75 each, with a $300 bonus per repository once more than 5 of its tasks are approved. Read this page fully before your first task.

## Overview & payout

A task is a change to your codebase — a feature request, bugfix, or enhancement — packaged so that an engineer (or an automated agent) can attempt it from the instruction alone, and a sealed verifier can grade the attempt pass or fail with no human judgment. You supply three things: the instruction, a reference solution patch proving the task is solvable, and new tests that fail before the change and pass after it.

1. Connect a private repository (one-time per repo).
2. Publish an environment: a dependency-setup Dockerfile pinned to a base commit.
3. Author the task in the in-browser workspace and submit.
4. Watch the validation pipeline live; revise and resubmit if a stage fails.
5. A human reviewer makes the final call.

Payout: $75 (USD) per approved task, recorded at approval and paid on the normal payment cycle. Each repository additionally pays a one-time $300 bonus once more than 5 of its tasks are approved. A repository can hold up to 10 tasks, so a fully-worked repo is worth up to $1,050.

## Connect your codebase

Tasks are authored on private repositories you own, connected through your GitHub authorization. Public code is not eligible: a public repository, a fork of one, or code that otherwise already exists publicly will be rejected — the value of your tasks comes precisely from the code never having been seen before.

- **What we access:** a read-only snapshot of the repository pinned to a single commit, plus repository metadata (language, size, history) used for eligibility. Access rides your GitHub authorization; you can revoke it at any time.
- **Privacy:** your code is stored privately, used only to build and validate your tasks, and never redistributed. Task environments are built into a private registry.
- **Ownership:** by connecting a repository you attest that you own the code or hold full rights to contribute it for this purpose.

**Eligibility requirements at connect time:**

- Primary language: TypeScript, JavaScript, Python, Go, or Rust.
- At least ~8,000 lines of first-party source across 50+ source files.
- At least 50 commits and two weeks of history — real projects, not scaffolds.
- Actively developed on GitHub, with history that accrued as the work happened. A codebase built locally and pushed all at once is not eligible.

## Environments

An environment turns your repository into a reproducible container image. You author only the dependency-setup Dockerfile; the platform owns checking out your repository at the base commit you choose and placing it at `/app`. Pick a base commit deliberately — every task built on this environment version is defined against it.

Dockerfiles are automatically checked. The rules:

- Exactly one `FROM`, using the language default (`python:3.12-slim`, `node:24-bookworm-slim`, `golang:1.25-bookworm`, `rust:1.92-slim-bookworm`) or any public base pinned by digest (`@sha256:…`). You are not limited to the default versions: to use any other image or version, find its digest with `docker pull python:3.9-slim` then `docker inspect --format '{{index .RepoDigests 0}}' python:3.9-slim` and put the printed `@sha256:…` on your `FROM` line.
- Keep it small: at most 20 KB, 200 lines, and 30 `RUN` steps.
- Pin installs: exact versions for pip / npm installs; `apt-get` with `--no-install-recommends`.
- No `curl | sh`, no `ADD` from URLs, no privileged tooling, no long encoded blobs or dynamic eval.
- No `git clone` or fetching repositories — the platform supplies your repo. No copying tests or solutions into the image.
- Do not swallow errors (`|| true`) — a broken install must fail the build, not surface later inside a task.

After the static checks, an automated review screens the Dockerfile, the image builds, and on success the version is published and available to new tasks. Builds are visible live from the repository page. Each new Dockerfile submission creates a new version; existing tasks keep the exact image they were built on.

## Authoring a task

Creating a task (pick repository, published environment, task name, category) seeds a draft workspace with the complete bundle. Most files are generated and must stay untouched — the automated checks regenerate and byte-compare them. You edit five:

| File | Description |
|---|---|
| `instruction.md` | The task instruction, written like a real work request (see the skeleton below). Must end with the generated IMPORTANT line. |
| `solution/solution.patch` | Your reference solution as a unified diff against the base commit. Every fail-to-pass test must pass with it applied. |
| `tests/test.patch` | A unified diff ADDING your new tests at the base commit. Applied only inside the verifier — the solver never sees these tests. |
| `tests/config.json` | The graded test ids: `f2p_node_ids` (new tests) and `p2p_node_ids` (existing tests that must keep passing), plus the report format. |
| `tests/test.sh` | Only the marked RUN TESTS middle section — the commands that run your suite and write the report files. |

Generated and frozen: `task.toml`, `pre_artifacts.sh`, `environment/Dockerfile`, `tests/grader.py`, `tests/Dockerfile`, `solution/solve.sh`, and the frame of `tests/test.sh`. Fill in the two `task.toml` metadata placeholders (display title and description); everything else in it is fixed.

Write the instruction the way you would brief a capable colleague. Open with the problem or the need, then describe the finished behavior: inputs, outputs, edge cases, error handling, precisely enough that an engineer who has never seen your change could implement it from the text alone. Name the public surface your tests exercise (commands, endpoints, exported names, output shapes, exact strings your tests match) naturally in prose, and leave file layout, helper names, and other internal decisions to the implementer: any correct implementation shape must be able to satisfy the text. Never reference your tests, hidden files, or external links. Write it in your own words and your own structure: flowing developer prose, no fill-in template, no numbered requirement ledger. A worked example:

> Add per-token rate limiting to the public API.
>
> Right now requests to `/api/v1/*` are served unconditionally, so a single token can issue unlimited requests. We want requests beyond 60 per rolling minute per API token to get an HTTP 429 with body `{"error": "rate_limited", "retry_after_seconds": <n>}`. The window is per token, not per IP; unauthenticated requests share one global bucket of 10 per minute. Responses under the limit must be unchanged apart from a new `X-RateLimit-Remaining` header, and existing endpoints keep their current response shapes for admitted requests. Limits should be configurable through the existing config module.
>
> Two boundary cases matter: a request that arrives exactly as the window resets is admitted, and clock skew between workers must not double-count a request against the window.
>
> IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.

**Why this reads like a strong task.** The strongest instructions are dense work requests; yours should read the same way. Each part of the example above earns its place — aim for the same density:

| Element | Why it matters |
|---|---|
| Opens with the goal | The first sentence names the behavior to build ("Add per-token rate limiting"), not the defect. The goal is clear immediately. |
| Developer prose, your own shape | Written the way you would brief a colleague: flowing prose, no header template, no bullet checklist. State the contract (observable behavior), not a sequence of edit steps, so any correct implementation shape can satisfy it. |
| Exact observable values | 60 requests/minute, HTTP 429, the literal JSON body, the `X-RateLimit-Remaining` header. Concrete numbers and output shapes, but no internal module layouts, helper names, or struct fields; where the change lives is the solver's job to discover. |
| Named edge cases | The window-reset boundary and cross-worker clock skew are spelled out, giving the tests precise, non-obvious conditions to check. |
| Existing behavior stays green | Under-limit responses stay unchanged, and your verifier must actually check that by running the repository's existing suite as regression cover. |
| Self-contained and tight | Nothing points at the held-out tests, internal files, commit history, or external links, and it stops once the contract is stated. A spec that enumerates everything measures transcription, not engineering. |

The final line is load-bearing and must be kept exactly as generated — committed work is the only thing the verifier ever sees:

> IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.

## Scope requirements

Tasks must be substantial, multi-file engineering work — not one-line fixes. The automated checks enforce these minimums:

| Requirement | Minimum |
|---|---|
| Reference solution | ≥ 459 added lines, across at least 4 files |
| Held-out tests | ≥ 596 added lines, across at least 2 test files |
| Instruction | 100 – 300 words, and aim near 250. A strong instruction states the required behavior and stops; padding toward the cap reads as a spec dump and hurts review. |
| Instruction-to-solution balance | 0.9 – 7.5 added solution lines per instruction word. A short spec driving a deep change is the goal; a spec that narrates the implementation line by line is rejected. |
| Fail-to-pass tests | At least 8 named tests, and aim for 20+ |
| Pass-to-pass tests | At least 50 tests that stay green. Pin the full existing suite, and add regression tests if the repository has fewer |
| Time budget | Fixed platform standard: 90 minutes for the attempt, 30 minutes for verification |

These are floors, not targets — tasks near the minimums on every dimension tend to be rejected on quality.The resource envelope (CPU, memory, timeouts) is identical for every task and is not editable.

## Verifier contract

- **Binary outcome.** The reward is 1 if and only if at least one fail-to-pass test is listed, every fail-to-pass test passes, and no pass-to-pass test fails. Anything else is 0 — there is no partial credit.
- **Fail-to-pass (F2P):** your new tests. Each must fail at the base commit and pass with your reference solution applied. **Pass-to-pass (P2P):** tests that stay green on both sides, the proof your change doesn't break the codebase. Usually the repository's existing tests, but any test that passes on both sides counts, so a thin suite is something you can top up rather than a dead end.
- **Pin the whole suite, not a sample.** Grading counts only the ids listed in `p2p_node_ids` — an existing test that runs but isn't pinned contributes nothing, even if it fails. Run the repository's full existing suite as the base selection and list every test id its report emits. A hand-picked subset leaves the rest of the codebase unguarded and is rejected at submit.
- **Named reports, absence = failure.** Grading reads per-test named reports (CTRF or JUnit). A listed test id absent from every report counts as failed; skipped counts as failed. Silencing or dropping tests can never help.
- **Behavioral surface only.** Tests assert through public APIs and observable outputs — not private helpers or symbol names. Any behaviorally-correct implementation must pass, including ones shaped nothing like your reference solution.
- **Sealed verification.** Tests are applied only inside a separate verifier container; the solver's environment has no path to them. Test-runner configuration tricks (early exits, report suppression, framework config edits) are detected and rejected.

## The pipeline

Every submission runs the full pipeline before human review. Each stage is visible live on the task page, including per-trial progress and the job directory of every run.

1. **Automated checks** — required files, frozen-file integrity, configuration values, patch scope floors, instruction bounds, blocked terms. Instant feedback at submit.
2. **AI check** — the instruction file is screened for AI-generated text. Write the instruction in your own words; flagged submissions are rejected.
3. **Originality** — the task is compared against previously submitted tasks (instruction wording and the set of files the patches change). Near-duplicates of anyone's task, including your own live ones, are rejected. Submit original work.
4. **Reference verification** — your reference solution and the unchanged repository each run three times on the real harness: the reference must pass every run, the unchanged repository must fail every run. Any deviation (including flakiness across the repeats) fails the stage.
5. **Quality review** — an automated reviewer reads the entire bundle against a quality rubric: instruction/test alignment, instruction writing quality (it must read like a real work request in natural, concise, behavior-focused prose, not a padded or templated specification), verifier integrity, test structure, environment cleanliness. Blocking criteria reject; advisory ones are surfaced to the human reviewer.
6. **Calibration (two rounds)** — independent automated attempts at the full time budget establish where your task sits. A task solved too often is too easy and fails. A task solved too rarely is above the accepted difficulty range and also fails. Only tasks inside the target range proceed.
7. **Run audit** — the unsuccessful calibration attempts are audited: genuine difficulty passes; failures caused by a broken environment, a flaky verifier, or a grading defect fail the task.
8. **Human review** — a reviewer makes the final call. Rejections always include a written reason.

Failures are classified: verdict failures are about the task; infra failures are platform flakes, never count against you, and get re-run.

## Quality bar & pitfalls

- **Write the solution fresh.** The reference solution must be authored for this task. Picking a base commit just before a change you already shipped and submitting that existing change is checked for and rejected — the solution must not be derivable from your repository's history.
- **Self-contained instruction.** No references to hidden tests, issue or PR links, or anything the solver can't see. If the tests check it, the instruction must specify it.
- **Deterministic tests.** The verifier runs repeatedly during validation; variance across identical runs reads as flaky and fails. No timing assumptions, no network, no ordering dependence.
- **Green base for P2P.** Every test you list as pass-to-pass must actually pass at the base commit in your environment, and a red base fails reference verification. Tests you add to reach the floor must cover behavior that already works, so they pass with and without your solution.
- **Disjoint paths.** Your test patch and solution patch must not touch the same files, and the test patch should only add test files.
- **No internal names.** Bundle content is scanned for blocked terms — nothing in it may reference this program, platform, or evaluation vocabulary. Write the task as if it were a normal ticket in your repository.
- **Aim past the floors.** The strongest tasks specify a coherent feature with real edge cases, 20+ fail-to-pass tests, and an instruction an engineer could implement from cold.

## Review & payment

Tasks that clear the pipeline enter an independent review queue. Reviewers see your bundle, the pipeline results, and every run — and approve or reject with a written reason. If your task fails validation, you can revise the draft and resubmit. You cannot submit a second task whose content is identical to one you already have in review or decided.