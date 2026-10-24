# CAD commit recovery

`commit_to_document` captures the complete configuration response and its
`sourceMicroversion` before its first configuration POST. When the account
budget permits, it first creates a `darwin-pre-<hash>-<timestamp>` Onshape
version. A later commit failure triggers a fresh configuration GET, one restore
POST built from the saved quantity values/defaults, and a final read-back check.

If restoration and verification succeed, the commit still returns `failed` and
`regen_status="ERROR"`; it never reports a successful commit. If recovery fails,
the result is `failed` with `regen_status="PARTIAL_WRITE"`. The `GeometryRef`
contract has no dedicated manual-recovery field, so its `error` includes:

> MANUAL RECOVERY REQUIRED: Onshape version graph → restore to the named
> pre-write version.

Use the named `darwin-pre-...` version in the document's version graph to restore
the workspace. If the ledger refuses the pre-write version before the
configuration POST, the write is not attempted and the result is
`NOT_ATTEMPTED`; no restore is needed. If a write was attempted without a
confirmed checkpoint and automatic recovery also fails, the error includes the
saved quantity current/default values to restore manually. The commit result
contains no document URL or identifier.

`preview_commit` returns the manifest/design-space name as the redacted target,
the current-to-proposed configuration diff, expected API call count, and checks
planned. It performs at most one configuration GET and caches that response in
process; a cached preview performs zero calls. Preview errors are returned as an
`error` field and do not permit a write.

Recovery uses only quantity configuration values because the existing write
contract is quantity-only. Any unexpected or incomplete quantity shape fails
closed and produces the partial-write/manual-recovery result.
