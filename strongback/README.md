# strongback

A deterministic construction progress-billing, retainage and payment-application
engine, in pure Python with no runtime dependencies.

A pay application looks like arithmetic and is not.  The schedule of values is
fixed, the field reports a percentage, and yet two competent people produce two
different cheques from the same month's work — because the contract's words
resolve differently:

* *Retainage shall be reduced to five percent at fifty percent completion.*
  Does the reduction apply only to work billed after the threshold, or is the
  whole balance re-rated and the difference released?
* *Materials suitably stored on the site may be included.*  When does stored
  material stop being stored — when the field says so, or in proportion to the
  line's completion?
* *Less previous certificates for payment.*  Certified, or actually paid?
* *Work directed by the owner.*  Billable when directed, when approved, or only
  when executed?

None of those has a default that is right everywhere.  strongback makes each of
them an explicit setting, computes an application from the documents plus the
settings, records every decision it made, and can run the same job twice under
two readings and price the difference line by line.

```
                          contract + schedule of values
                                      |
    field reports  ---->   progress   |    <---- stored materials ledger
                                      v
                                  retainage  <---- retainage clause + policy
                                      |
     back-charges, offsets, tax ---> billing ----> continuation sheet + summary
                                      |
                                  payments  ----> due dates, aging, interest
```

## Quick start

```console
$ python -m strongback demo --periods 3
$ python -m strongback bill 3 --sheet
$ python -m strongback explain 3 --line 03300
$ python -m strongback compare 4 aia_standard owner_favorable --attribute
```

Every command runs against a built-in sample job — a two-and-a-half million
dollar shell-and-core contract with a retainage step-down, stored switchgear, a
change order that is directed before it is executed, a unit-price line that
overruns, and a disputed back-charge.  Point any command at your own run
document with `--file`.

In code:

```python
from strongback import money, monthly_schedule, RunContext, run_contract
from strongback.dataio.samples import sample_contract, sample_progress

context = RunContext(
    sample_contract(),
    monthly_schedule("2024-09-01", 3, through_day=25),
    progress=sample_progress(3),
)
for result in run_contract(context):
    print(result.application.id, result.payment_due())
```

## What it does

* **Values progress** three ways — a judged percentage, a measured quantity on a
  unit-price line, and an event on a milestone line — with the over-billing,
  under-run and overrun rules stated rather than assumed.
* **Handles stored materials** with eligibility (on site, off site, insured),
  a ceiling against the line's scheduled value, and three conversion rules for
  when stored value becomes work in place.
* **Accrues retainage** over the whole billing history, so a step-down can be
  read prospectively or retroactively, a ceiling can bind, and a line can carry
  its own rate.
* **Applies deductions** where the contract puts them: a back-charge before
  retainage, after retainage, or out of retainage held; offsets that reverse and
  offsets that do not; sales tax that attaches on delivery or on installation.
* **Produces the documents** — a continuation sheet and a nine-line summary that
  agree with each other by construction.
* **Gates payment** on lien waivers, insurance certificates and statutory
  notices, as holds rather than as deductions.
* **Tracks payment** — due dates from three start events on two calendars,
  receipts, allocation across open applications, aging, prompt-payment interest,
  pay-when-paid and pay-if-paid.
* **Explains itself.**  Every run carries a trace of the decisions it made, and
  `strongback explain` reads it back per line.
* **Compares two readings** of the same documents and attributes the difference
  to individual settings, reporting the interaction residue rather than smearing
  it across the parts.

## The conventions

Forty-one settings, grouped, each with allowed values, a default and a sentence
saying what turning it does:

```console
$ python -m strongback policy --knob stepdown_certification
$ python -m strongback policy --profile public_works --changed
$ python -m strongback policy --profile aia_standard --against lender_draw
```

Five profiles bundle them the way real contracts do — `aia_standard`,
`owner_favorable`, `subcontractor_favorable`, `public_works` and `lender_draw`.
A profile is a starting point; any setting can be overridden with `--set`.

The engine never reads a setting directly.  Policy builds small options objects
and hands them to the computing modules, none of which imports policy, and none
of which has a default of its own to fall back on.  That inversion is what makes
`compare` meaningful: two runs of one context differ only where a named
convention differs.

## Layout

| package | what lives there |
| --- | --- |
| `core` | exact money, rates, quantities, dates, working calendars, the trace |
| `model` | parties, contracts, schedules of values, change orders, terms |
| `progress` | field observations, valuation, stored materials, cost-to-cost |
| `retainage` | the clause as data, the base, step-downs, releases, the ledger |
| `deductions` | back-charges, offsets, tax, allowance reconciliation |
| `billing` | continuation rows, the summary page, applications, revisions |
| `payments` | due dates, receipts, allocation, aging, interest, pay-chains |
| `waivers` | the four documents, the exchange, the exposure |
| `compliance` | insurance, statutory notices, payment gates |
| `wip` | earned revenue against billing, forecasting, over/under |
| `policy` | the settings, the profiles, and how they resolve |
| `engine` | the order the work happens in |
| `explain` | reading a run's trace back to a person |
| `compare` | two policies on one job, priced and attributed |
| `dataio` | JSON round trip, CSV doors, the worked sample |
| `report` | plain text for people |
| `cli` | an argument surface over all of it |

## Determinism

A run is a function of its inputs.  Nothing in the package reads a clock, a
random number or an environment variable — a hygiene test enforces that by
walking the syntax tree — and the suite checks that two runs of the same job
produce identical figures, identical traces and byte-identical reports, under
different interpreter hash seeds.

## Running the tests

```console
$ python -m unittest discover -s tests -t .
```

The suite is 900-odd tests plus every doctest in the package, and it needs
nothing that is not in the standard library.  `pytest` works too.

## Not implemented

Deliberately.  Each of these is a feature the package plausibly should have and
does not, kept written down so it stays visible:

1. **Subcontract tier billing.**  `model/subcontract.py` records flow-down and
   scope shares, but no engine builds a subcontractor's application from a prime
   run, and nothing computes what a sub is owed when the prime is paid short.
2. **Escrowed retainage.**  Retainage held in an interest-bearing account, with
   the interest running to the payee, and the escrow reconciled at closeout.
3. **Lender draw funding.**  A budget with funding sources, an interest reserve,
   and draw requests that can be short-funded independently of what was
   certified.
4. **Bonded stored materials.**  Warehouse receipts, inspection certificates and
   the bonding that makes off-site storage billable in the first place.
5. **Certified payroll.**  Prevailing-wage schedules, weekly payroll reports and
   a compliance gate that holds a payment until they are filed.
6. **Schedule-of-values re-baselining.**  Reallocating scheduled values between
   lines mid-job without destroying the audit trail of what was billed against
   the old ones.
7. **Multi-currency contracts.**  A contract billed in one currency and paid in
   another, with the conversion policy and the exposure stated.
8. **Punchlist tracking.**  Item-level punchlist with values, so the closeout
   holdback follows the actual remaining work rather than a single figure.
9. **Cash-flow forecasting.**  Projected billings and projected receipts by
   month, from the schedule, the payment terms and the observed payment history.
10. **Change-order pricing build-ups.**  Labour, material and equipment detail
    with tiered markup, so a change order's price can be audited rather than
    accepted.

## Licence

MIT.  See `LICENSE`.
