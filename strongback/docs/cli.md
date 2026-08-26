# The command line

```console
$ python -m strongback COMMAND [options]
```

Exit codes: `0` clean, `1` ran and found something (a gate holding a payment, a
document that will not validate), `2` the invocation was wrong.  A script can
therefore tell "this job has a problem" from "you typed the command wrong".

Every command takes `--file PATH` to read a run document, and falls back to the
built-in sample job when none is given.  Most take `--profile NAME` and one or
more `--set knob=value` overrides.

| command | what it prints |
| --- | --- |
| `demo` | the sample job end to end |
| `validate` | problems with a contract and its ledgers |
| `schedule` | the schedule of values at a period, as a table or CSV |
| `progress` | reported progress and the value it produces |
| `bill N` | the application for period N, optionally with the sheet and gates |
| `retainage` | retainage held by line, or the movement period by period |
| `waivers` | the waiver log and the unreleased exposure |
| `payments` | open items, aging and interest |
| `wip` | earned revenue against billing |
| `compare N A B` | the same period under two policies, optionally attributed |
| `explain N` | why the numbers are what they are |
| `policy` | profiles, settings, and what each setting does |
| `summary` | a one-page picture of the job |
| `closeout` | retainage, waivers and offsets still open |
| `export` | the run, an application, a sheet or a schedule as data |

## Worked sequence

```console
$ python -m strongback validate
$ python -m strongback schedule --period 3
$ python -m strongback bill 3 --sheet --gates
$ python -m strongback explain 3 --line 05100
$ python -m strongback retainage --movement
$ python -m strongback compare 4 aia_standard owner_favorable --attribute
$ python -m strongback export run > job.json
$ python -m strongback bill 4 --file job.json
```

## Overriding a convention

```console
$ python -m strongback bill 4 --set stored_conversion=proportional
$ python -m strongback bill 4 --profile public_works --set previous_basis=certified
$ python -m strongback policy --knob stored_conversion
```

An unknown setting or an unallowed value is a usage error, not a silent
fallback.

## About that exit code 1

The sample job bills a unit-price excavation line at 12,400 cubic yards against
an estimate of 12,000, and the default overrun rule bills what was measured.
That takes the line past its scheduled value, which `bill 3` and `bill 4` report
as a diagnostic and exit `1` for.  It is not a bug in the sample; it is the
finding the exit code exists to surface.  Under `--set unit_overrun_rule=capped`
the same job bills to the estimate and exits `0`.
