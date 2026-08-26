# Design notes

## One direction of dependency

```
core -> model -> progress -> retainage -> deductions -> billing -> payments
                                                     -> waivers  -> compliance
                                                     -> wip
policy -> (options objects) -> engine -> explain / compare / report / cli
```

Nothing below `policy` imports it.  The computing modules take their conventions
as arguments — `ProgressOptions`, `StoredOptions`, `RetainageOptions`,
`WaiverRequirement` — and have no defaults of their own to reach for.  A source
hygiene test enforces the rule by reading the imports.

The payoff is `compare`: the same `RunContext` can be re-run under a second
policy in the same process, and every difference in the output is caused by a
setting that can be named and priced.  A module with a hidden default would
break that silently.

## Cumulative, never incremental

Nothing computes a "this period" figure directly.  Every to-date figure is
computed from the ledgers, and the period figure is the difference between two
of them.  That is what makes a corrected prior period propagate instead of
double-counting: revise application 4 and applications 5 onward move, because
they were never storing their own history.

The same reasoning drives the retainage accrual, which takes a *series* of
periods rather than one.  Under a prospective step-down, what is held today
depends on what was held before, so a run recomputes the whole history each
time rather than reading a stored balance that has drifted.

## Rounding is a stage, not a step

`Money` keeps whatever precision arithmetic produced.  Rounding happens where a
document is produced, and which stage that is — per line or once on the summary
— is a policy setting.  Rounding on every intermediate step gives a defensible
and wrong answer, and it is the usual cause of a continuation sheet that
disagrees with its own summary by a few cents.

## The trace is part of the answer

A run records each decision as it makes it: the stage, the subject, a sentence
and the numbers behind it.  The trace is deterministic, serialisable and free of
anything that varies between runs, so `strongback explain` reads it back rather
than reconstructing a plausible story afterwards.  If the narrative and the
numbers ever disagree, the narrative is the bug.

## Gates hold; deductions reduce

A missing lien waiver, a lapsed certificate and an unfiled notice do not change
what is owed.  They hold the payment.  Keeping them out of the money is what
makes closeout tractable: what was held for a lapsed certificate is still owed
the day the certificate arrives.

## Determinism

No clock, no randomness, no environment.  Where a real system would call
`today()`, this one takes an `as_of` argument and makes the caller say what day
it is.  Dictionary iteration is sorted wherever it reaches output.  Two runs of
the same job produce identical figures, identical traces and byte-identical
reports, and the suite checks that under different interpreter hash seeds.
