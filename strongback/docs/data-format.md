# The run document

A run document is JSON: the objects' own `to_dict` output, so a dump-load round
trip is lossless and testable.  Write one with `strongback export run`.

```json
{
  "contract": {
    "id": "C-2024-118",
    "title": "Harbor Point Phase II -- shell and core",
    "currency": "USD",
    "payer": {"id": "OWN", "name": "Harbor Point Holdings LLC", "role": "owner"},
    "payee": {"id": "GC", "name": "Keel & Sons Construction", "role": "contractor"},
    "billable_threshold": "executed_only",
    "schedule": [
      {
        "code": "03300",
        "description": "Slab on grade",
        "scheduled_value": "265000",
        "kind": "lump_sum",
        "stored_eligible": false,
        "group": "Structure"
      }
    ],
    "retainage": {
      "base_rate": "10.00%",
      "stored_materials_retained": true,
      "basis": "work_and_stored",
      "stepdowns": [{"threshold": "50.00%", "rate": "5.00%", "mode": null}],
      "stepdown_mode": "prospective",
      "release_at_substantial": "90.00%",
      "punchlist_multiple": "1.5"
    },
    "payment_terms": {"net_days": 30, "day_basis": "calendar", "start_event": "certification_date"},
    "change_orders": [],
    "completion": {"notice_to_proceed": "2024-09-16"}
  },
  "periods": [
    {"number": 1, "start": "2024-09-01", "end": "2024-09-30", "through": "2024-09-25"}
  ],
  "policy": {"profile": "aia_standard", "settings": {}},
  "progress": [{"code": "03300", "period": 1, "shape": "percent", "basis": "to_date", "percent": "40.00%"}],
  "stored": [],
  "costs": [],
  "backcharges": [],
  "offsets": [],
  "waivers": [],
  "applications": [],
  "revisions": []
}
```

## Conventions in the format

* **Money is a decimal string.**  Never a float — a float loses cents, and the
  loader refuses one.
* **Rates carry a percent sign.**  A bare `1` is ambiguous between one percent
  and a hundred; writing `100.00%` removes the guess and round-trips exactly.
* **Dates are ISO.**  Nothing else is accepted and nothing else is written.
* **Keys are sorted on output.**  Two dumps of the same run are byte-identical,
  so a diff of two exports shows what actually changed.
* **Unknown top-level keys are refused** rather than ignored, because a
  misspelled section that is silently dropped is worse than an error.

## CSV doors

Two narrow readers for what actually arrives from estimating and project
management systems:

```console
$ python -m strongback schedule --csv > sov.csv
$ python -m strongback export sheet --period 3 > continuation.csv
```

`read_schedule_csv` needs `code`, `description` and `scheduled_value`;
`read_progress_csv` needs `code`, `period` and exactly one of `percent`,
`value` or `quantity`.  Both name the offending row number when something is
wrong.
