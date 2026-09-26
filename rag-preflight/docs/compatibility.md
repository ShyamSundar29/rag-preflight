# Public contracts and stored-format policy (0.1.0)

The supported Python API is the set exported by `rag_preflight.__all__` and
documented in [API notes](api.md). Documented CLI commands, exit codes, JSON
report fields, and the [finding codes](failures.md) are also public interfaces.
Modules not exported there are implementation details. A finding's `code` is a
machine identifier: CI rules may depend on it. New codes may be added; renaming,
removing, or changing the blocking severity of an existing code requires a
documented deprecation and migration path. Deprecation will be announced in the
changelog and retained for at least one minor release where feasible. An error
will not silently become suppressible by a warning baseline.

The initial deletion defaults are 25% per document and 15% for ordinary
corpus-wide removals, with no default absolute ceilings. They are configurable
starting policies, **not** universal safety guarantees. Published defaults will
not silently change in a patch or minor release. A future policy revision must
be opt-in or part of a documented major-version migration with explicit
before/after behavior. Applications should pin their own thresholds and review
the effective policy recorded in every plan.

Stored formats carry schema versions. Writers emit the current version. Readers
accept known older versions only through an explicit, tested migration that
preserves safety meaning; otherwise they reject the file. Unknown newer versions
fail with the version number and reader capability so an older binary cannot
misinterpret new fields. Version 1 portable snapshots have an exact field set
and revision hash; unknown extra fields in version 1 remain invalid. The current
reader supports snapshot version 1 only. SQLite ledger schema 1 migrates to 2
atomically; use a backup before opening an older ledger. Warning-baseline
schema 1 retains original strict fingerprint semantics when read by schema 2.
No future schema migration is promised until it is implemented and tested.

These rules define the 0.1.0 public contract. They do not imply production history
or broad external review.
