# EconML #686 baseline prerequisite measurement

This packet measures public, unchanged source at
`0b45f8343e08ebcdb93ae859643a0efe20c21e7d` on one native Linux AMD64 hosted
runner. It contains no proposed product fix and makes no claim that #686 is
resolved. It is not the eventual full validation of the proposed change.

The source is checked against 299 recorded Git blob identities. Python 3.13.16,
uv 0.13.6, the 71-package hashed runtime closure and five exact build constraints
are fixed. Runtime virtual environments deliberately omit pip bootstrap; uv is
separate. Compiled imports, a real Numba JIT, LightGBM, four actual xdist workers
and offline Ray initialization must pass before the complete Ray-marked group.
No tests or markers are substituted. The wheel smoke, when sufficient time
remains, uses an isolated environment outside the source tree; it is not a
manylinux/cibuildwheel result.

The controller reuses the byte-identical bounded command helper from a previously
successful hosted validation. Before project execution, the same controller
exercises real 20-second success, exit-3 dependency blocking, 256 MiB OOM,
timeout and compressed-deadline paths. Its outer 50-minute budget never resets.
The first failure and the owned container's final stop state are retained.
There is no periodic monitoring writer.

The venue intentionally avoids the Mac's protected external Docker disk. Only
the isolated hosted runner's labelled work volume and image are used. A
hash-recorded image archive is retained as a separate artifact so a later
baseline/candidate run can restore the exact image. No container, volume or
image is removed by this packet. A failed packet is closed; it does not rerun.

Host admission requires four CPUs, at least 15 GiB assigned memory, 14 GiB
available and 20 GiB disk free. Containers are sequential, nonroot, read-only
root, capabilities dropped, no-new-privileges, with no ports, credentials,
Docker socket or host namespaces. Only dependency installation has bridge
network access; build, probes, Ray tests and wheel verification are offline.
Ray gets a 12 GiB no-swap hard cap, 4 GiB shm and 8192 PIDs. Kernel peak and
limit-event measurements require interpretation: pre-warmed file cache is not
a guarantee of peak memory for a later cold parallel run.

Completing M0 still requires review of all actual results, especially any
baseline test failures. Later work retains all six Python 3.13 groups, the
Python 3.9 floor, whole-repository Ruff, an off-source wheel test, complete
baseline/candidate Sphinx doctests and relevant notebook coverage. No current
upstream CI result is substituted for fresh validation. Selection timing is
uncertain: recent outside documentation PRs merged quickly, while our existing
code PR #1063 has not received review for about 49 days.

Ray memory-monitor intervention (`ray.exceptions.OutOfMemoryError` or workers
"killed due to memory pressure") and xdist native-worker crashes are HOLD,
including when pytest exits 1 and the kernel reports no OOM kill. Such a run
cannot supply a baseline-failure classification or memory-cap sizing.

The one-shot latch requires a push event, workflow run number 1 and attempt 1.
The diagnostic branch must contain only this packet's manifest paths. Labelled
Docker objects last until hosted-runner teardown; durable artifacts last seven
days. Later image reuse must verify the image ID after load, not assume a gzip
digest is reproducible. The 4 GiB shm cap differs from the CI host's layout.
