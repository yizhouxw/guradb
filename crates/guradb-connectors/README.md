# Rust fixed-source metadata kernel (M-F0)

Status: **implementation draft; compilation and independent validation pending**,
Refs #123. The contract below was written before the implementation.
This is an internal pure kernel. No SQL/HTTP endpoint, production reader route,
object provider, or Python fallback changes. The existing M0 decoder is unchanged.

## Input and result contract

- Consume an already validated common `cf1a/1.0` `read_binding` Contract and
  caller-supplied canonical metadata bytes, in the binding's source order.
- The source descriptor is `manifest/1`; its metadata is `p04-fixed/1`.
  These are different version identifiers. Never discover files or rebind latest.
- Validate the closed manifest, complete physical schema and field-ID mapping,
  source identity/schema digest, metadata byte length/SHA-256, and exact revision
  object membership. Matching bytes do not prove external retention or authority.
- Preserve 1–2 sources, total metadata <=64 KiB, <=4 files, <=16 row groups,
  <=1000 rows, <=4 MiB file bytes and <=32 physical fields across sources.
  Each data file is <=1 MiB. Empty sources remain valid.
- Map caller-supplied typed physical cells through the same mapping for ordinary
  and future located output. Reuse common `Cell`, `Record`, and `encode_key`.
  Stable ID/version never use physical row positions. Derived versions use the
  fixed revision; duplicates are checked across the supplied complete source set.

Reject missing/unknown/duplicate metadata fields, noncanonical JSON, floats,
negative or unsafe metadata integers, malformed/duplicate physical field IDs,
wrong source/schema/object membership, unsupported versions, delete files,
schema evolution, invalid/NULL stable keys, duplicate logical IDs, type errors
and nonnullable NULL. Object shapes/ranges and resource mapping authority remain
in common. The kernel does not authenticate descriptors or retain source bytes.

The metadata parser checks byte/structural limits before allocating its JSON
tree. This is a bounded parser, **not** a certified parent memory/time budget.
No authorization, parent Control/ledger, cancellation, object GET, Parquet page
decode, Arrow provider, locator, pagination or output delivery is implemented.
Pure row mapping checks only supplied cells; it cannot prove those cells were
actually read, complete or from unmodified Parquet objects. These obligations
remain with the later real storage/source/query pairing.

## Verification mapping and compatibility

| Contract | Planned independent evidence |
| --- | --- |
| Closed manifest, field ID/schema/source/object binding | Fixed canonical inputs derived from existing PyArrow fixture contract and common golden binding; independent expected totals and mutation negatives |
| Stable keys/version/NULL/duplicate handling | Hand-calculated typed key bytes, int64 extrema, Unicode, cross-source duplicate and missing/type/NULL negatives |
| Fixed source limits | Exact boundary and one-over inputs for source/metadata/file/group/row/byte/field counts |
| Actual Parquet/transport/authorization/parent budget/stop | Not supplied by this kernel; requires independent real pairing |

The original full11 retrieval (<=100) and 130-row scan (64/64/2) are separate
acceptance paths. These unit fixtures do not certify either runtime path.
The connectors selector is pending at the starting SHA; auto requires system,
and an explicit module claim is rejected. Source, test, coverage and dependency
checks await their assigned resource window and non-author review. Keep Rust's
reviewed applicable-line 100% and Python's full production-source 80% threshold;
do not enlarge the original 21 Rust exclusions.

No stored format or user route is migrated. Python production paths remain
unchanged; deleting the new pure kernel is a code-only rollback. Retiring the old
reader needs an explicitly accepted runtime switch, real consumer comparison,
failure/budget/recovery evidence and exact-main verification. Module/fixture
results never imply pairing, system or release acceptance.

## Parser boundary test strengthening (Refs #167)

This test-only change adds no user behavior, production parsing rule, dependency,
format support, or runtime route. The seven-file #123 candidate is preserved as
the inherited, independently reviewed source baseline; its Rust execution and
coverage remain unverified. Only this README and test code change in #167.

Private parser cases use complete canonical JSON on both sides of each limit:
12/13 nested arrays, 4096/4097 scalar array elements (one opening delimiter plus
the separators gives exactly that structural counter), and 65536/65537-byte
quoted ASCII strings. The first input of each pair must parse; the second must
return `resource_limit`. These are parser unit fixtures, not valid p04 manifests
or proof of a production memory/deadline bound.

Separate full-manifest cases start with the existing valid fixture, mutate only
a numeric token or duplicate a same-value field, and bind the actual raw length
and SHA before checking rejection. Numeric/duplicate canonical violations must
return `invalid_contract`; truncation must return `corrupt_object`. A parser-sized
string still fails the closed manifest schema; its one-byte-over peer hits the
byte limit. Valid syntax, exact bounds and expected codes have independent
standard-library witnesses; none substitutes for running the Rust tests.

Planned self-test: `cargo test --locked --package guradb-connectors`, including
the original tests and these additions, in a separately granted resource window.
No compile/test/coverage or component/pair/system result is claimed by this
source-only update. Existing selector, whole-owner coverage, independent review,
normal hooks and exact-main verification obligations remain unchanged.

## 2026-10-26 local format-quality continuation

Local task `20261026-connectors-format-quality` imports the exact seven-file
source baseline from the abandoned F208-v3 worktree. Its retained lint attempt
failed `cargo fmt -- --check` with 56 diff blocks in four files; clippy did not
run. That historical failure and the earlier source-only contract remain valid.
This continuation applies only those formatting changes and records current
evidence here; public APIs, dependencies, rejection cases and runtime support
are unchanged. No user behavior or data migration is introduced.

Fresh package fmt followed by all-targets offline, locked clippy is pending.
Clippy compiles test targets and does not run the 21 library tests. Whole-owner
coverage, real pairing, system, normal hook and exact-main checks remain pending;
this local A exit cannot establish module/system acceptance or merge readiness.

The fresh local A attempt on 2026-10-26 completed package fmt check and
`cargo clippy --package guradb-connectors --all-targets --offline --locked -- -D warnings`
with native, CLI and container exit 0. The retained CLI has both output EOFs;
its owned container was exited with PID 0 and the exact source mapping, and the
bound source hashes matched before and after. This README-only result note is
after that bound snapshot; Rust and Cargo source bytes remain identical.
No Rust tests, coverage, real reader/transport pairing, system or exact-main
verification ran in this attempt. Independent review remains pending.

The format-quality continuation was subsequently reviewed independently for its
formatting delta and recorded evidence (`PASS_LIMITED_A`); that review did not
validate the entire manifest or mapping implementation. The present integration
has not rerun Rust tests or established a real reader or authorization path.
