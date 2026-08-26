Subcontracts link into prime contract schedule lines through `SubcontractLink` and `FlowDownPolicy`, but the engine cannot currently generate downstream subcontractor pay applications from a prime contract run or allocate partial prime receipts down to subcontractors.

We need a subcontract billing engine that builds periodic pay applications for each linked subcontractor from a prime run. For each covered schedule line, the subcontractor's earned work in place and stored materials must be calculated from its defined scope share. Retainage must follow the link's flow-down policy: `independent` evaluates the subcontract's own retainage terms, `mirror_rate` applies the prime's base retainage rate while keeping subcontract step-downs, and `mirror_all` adopts the prime's effective retainage rate and step-down thresholds. Total subcontract line shares exceeding one hundred percent must raise a `DataError`.

When an owner pays a prime application short, `allocate_subcontract_receipt` must distribute the received funds among active subcontractors. Under `pro_rata`, proceeds are allocated in proportion to each subcontractor's net certified amount for that period; under `line_item_trace`, funds are allocated strictly to the lines the owner approved. Joint checks must be credited against the named subcontractor's balance. When pay-when-paid is enabled, subcontractor due dates are deferred until the prime receipt date or a sixty-day long-stop from prime certification, whichever comes first.

Every subcontract pay application, retainage decision, and payment allocation must record its rationale in the run's trace.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
