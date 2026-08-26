# The conventions, and why each one is contested

This is the catalogue.  Every entry is a place where two competent people read
the same contract and produce different money, with the setting that decides it
and the file that implements it.

## Progress

**Percentages above a hundred** (`over_hundred`, `progress/method.py`).  A line
reported at 120% is either a data-entry error, an over-billing to be corrected
next month, or an honest report on a line whose scheduled value is wrong.
`clamp` bills to the scheduled value, `allow` bills what was reported, `error`
refuses to build the application.

**Progress that goes backwards** (`negative_progress`).  A correction is a real
event.  The observation layer accepts a negative *incremental* figure and
refuses a negative *cumulative* one, because "minus five percent to date" is not
a thing anyone means.

**Unit-price overruns** (`unit_overrun_rule`, `model/unitprice.py`).  Measured
beyond the estimate: bill it at the rate, cap it at the estimate, or allow a
stated variance and cap beyond that.  The underrun case is not symmetric —
nobody pays for excavation that was not excavated.

**Milestones** (`milestone_rule`, `model/milestone.py`).  A milestone earns on
an event.  A structure topped out on the twenty-eighth of a month whose
milestone is "complete and surveyed" earns nothing that month, and the
superintendent who bills eighty percent of it is not wrong about the work, only
about the contract.

## Stored materials

**Eligibility** (`stored_allow_offsite`, `stored_require_insurance`).  Material
on site is normally billable; material in a warehouse two states away usually is
not, unless it is bonded, insured and marked with the owner's name.

**The ceiling** (`stored_cap`).  A hundred-thousand-dollar switchgear delivery
against a seventy-thousand-dollar line bills seventy under a cap of one hundred
percent of the scheduled value.

**Conversion** (`stored_conversion`, `progress/stored.py`).  When stored value
becomes work in place: when the field reports it (`explicit`), in proportion to
the line's completion (`proportional`), or all at once when the line finishes
(`on_completion`).  The proportional rule is the one that silently disagrees
with the field, and it is a common default in billing software.

## Retainage

**The base** (`RetainageTerms.basis`, `retainage/basis.py`).  Work and stored
material, work only, or work excluding change orders altogether.

**The step-down** (`RetainageTerms.stepdown_mode`, `retainage/stepdown.py`).
The clause that means two different cheques.  Prospective: the new rate applies
to work billed after the threshold, and what is already held stays held.
Retroactive: the total becomes the new rate times everything to date, and
crossing the threshold releases the difference.  On a five hundred thousand
dollar contract at fifty percent complete, twenty-five thousand against twelve
and a half.

**Certification** (`stepdown_certification`).  A step-down conditioned on
certified satisfactory progress can be reached in one period and take effect in
a later one.

**The ceiling** (`retainage_apply_cap`, `RetainageTerms.cap_rate`).  A cap
expressed against the contract sum or against work completed.  The two diverge
whenever the job is not exactly at the ratio the drafter had in mind.

**Rounding stage** (`retainage_round_stage`).  Round each line and sum, or sum
and round once.  The difference is a cent or two between the continuation
sheet's retainage column and line 5 of the summary, and it is what an owner's
accountant writes back about.

**Release** (`release_at_substantial`, `punchlist_multiple`,
`retainage/release.py`).  A share released at substantial completion, a
holdback of one and a half or two times the punchlist value, or both — in which
case the larger holdback governs.  A punchlist worth more than the retainage
held releases nothing and never creates an obligation to hold more.

## Change orders

**Which ones bill** (`change_order_threshold`, `model/changeorder.py`).  Work
directed by the owner and not yet executed has been *done*.  Whether it may
appear on an application is: executed only, approved, directed, or the
contractor's proposal.  All four are written.

**Their retainage rate** (`RetainageTerms.change_order_rate`).  Change-order
work is often retained at a different rate from base-contract work, and
sometimes at none.

**Allowance reconciliation** (`allowance_markup_rule`,
`deductions/allowance.py`).  Markup on the difference, on the actual cost, or
already included.  Not symmetric: `on_difference` credits markup back on an
underrun, `on_actual` can leave the contract sum *up* on one.

## The summary page

**Line 7** (`previous_basis`, `billing/summary.py`).  "Less previous
certificates for payment" means what was certified or what was actually paid.
On a job where an application was certified short, the two differ for the rest
of the contract.

**Line 9**.  Balance to finish including retainage is a subtraction from the
contract sum; the balance a superintendent quotes is contract sum less completed
and stored.  Both are available, under names that say which is which.

## Deductions

**Back-charge stage** (`backcharge_stage`, `deductions/backcharge.py`).  Before
retainage, after retainage, or out of retainage held.  The three differ by
exactly the retainage rate times the back-charge.

**Disputed charges** (`backcharge_allow_disputed`).  Deducted now and argued
later, or held until resolved.

**Tax** (`deductions/tax.py`).  What is taxable, when the tax attaches
(delivery or installation), and whether retainage is computed on the
tax-inclusive figure.

**Offsets** (`deductions/offset.py`).  Reversible (a lien to be bonded off, an
expired certificate) versus absorbed (liquidated damages).  A system that lumps
them together tells the payee they are owed money they will never see.

## Payment

**When it is due** (`PaymentTerms`, `payments/due.py`).  How many days, counted
on which calendar, from which event.  "Net thirty from receipt of a properly
submitted application" and "thirty days after certification" differ by however
long the architect took.

**Allocation** (`allocation_order`, `payments/allocation.py`).  A short cheque
pays the oldest application, the newest, everything pro rata, or whatever the
remittance advice says.  The choice changes the aging report, the interest and
which application a waiver has to cover.

**Aging** (`aging_basis`).  From the due date — nothing ages until it is late —
or from the application date, which is what a contractor's bank wants.

**Interest** (`interest_day_count`, `interest_compounding`).  A year of 365
days, 360, or thirty-day months.  Simple or compounding.  A grace period
suppresses interest entirely rather than shortening it.

**Pay-chains** (`payments/chain.py`).  Pay-when-paid defers a due date and
matures at a long-stop; pay-if-paid can extinguish the obligation, in
jurisdictions that enforce it.

**Joint cheques** (`joint_check_credit`).  How much of a cheque naming the sub
and their supplier counts against the sub's balance: all of it, or only what
the sub actually banked.

## Waivers and compliance

**The exchange** (`waiver_exchange`, `waivers/requirement.py`).  A conditional
waiver with the application and the unconditional one for the previous payment;
an unconditional waiver before the cheque; or the unconditional one after it.
Somebody carries the gap in every arrangement.

**The through date** (`waiver_through_rule`).  Period end, the measurement
cutoff, or the payment date.  A waiver through 30 November does not cover work
done on 1 December.

**Effectiveness** (`waivers/ledger.py`).  A conditional waiver against an unpaid
application is a document on file that releases nothing.  Counting documents is
not the same as measuring exposure.
