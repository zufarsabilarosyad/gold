<<EDIT-ME>> Replace everything above the final IMPORTANT line with the task
instruction, written the way you would brief a capable colleague who has
never seen your change:

- Open with the problem or the need, then describe the finished behavior:
  inputs, outputs, edge cases, error handling. The reader has the full
  repository, so point at existing code where that helps.
- Name the public surface your tests exercise (new commands, endpoints,
  exported names, output shapes, exact strings your tests match) naturally
  in prose. Every behavior your tests check must be stated here, and every
  requirement you state should be something your tests check.
- Leave internal decisions to the implementer. Do not dictate file layout,
  helper or class names, private signatures, or exact wording of messages
  your tests never assert on. If a sentence is only writable because you
  have already seen the solution, cut it.
- Write flowing developer prose in your own structure: no header template,
  no numbered requirement ledger, no test references, no external links
  (issues, pull requests, docs behind a login). Stop once the contract is
  stated.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.