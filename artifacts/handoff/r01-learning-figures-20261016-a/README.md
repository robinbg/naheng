# R01 frozen learning-ledger figures

Private candidate: `candidate/tools/render_learning_evidence.py`. It has no third-party runtime dependency, does not import the current learning implementation, and never executes a candidate or a model. No production file or source lock was changed.

The manifest explicitly lists one to three **closed** A03 runs. Each arm supplies project-relative paths and SHA256 for `protocol.json`, `checkpoint.json`, `result.json` and its outer `command.json`. A self-named comparison run also requires its explicitly hashed `stdout.log`; the tool locates an exact terminal JSON `out` and `exit_code` record, not a substring. Pilot runs bind through the command's exact `--out` argument. No directory scanning or active-run discovery occurs.

The tool checks original 12+24 / high<=24 / 120 s / 1800 s budgets, nine coordinates, ten-second synthetic world, protocol/checkpoint/result hashes, ordered event and candidate identities, training-only labels, retry accounting, terminal counts, actual cost and elapsed-time consistency. UNKNOWN/failed utility and constraint values must remain null. Missing compute durations remain UNKNOWN and are excluded from a clearly labelled known-cost subtotal. The chart does not draw utility, profit advantages, confidence intervals or fabricated values.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
& ./.venv/Scripts/python.exe artifacts/handoff/r01-learning-figures-20261016-a/candidate/tools/render_learning_evidence.py --root . --selection artifacts/handoff/r01-learning-figures-20261016-a/current-two-arms.json --out artifacts/reports/learning-current-two-review
```

The output must not exist. Files are `learning.svg` (standalone static export), `ledger-summary.json`, original `selection.json` and `generation.json`. SVG and JSON include source code/protocol hashes, source RunIDs/evidence hashes, request/fidelity/status counts, and scientific N added=0. Per-case artifacts are **not** independently reverified by this renderer; it validates the supplied ledger and linked file identities. The SVG labels that boundary.

## Actual data already rendered

- `real-two-version-figures`: historical 0a2 and 9593 learned panels. They explicitly have different code hashes and are not a fair method comparison. 0a2 has 36 requests / 2 completed / 34 UNKNOWN / 24 high / known cost 422.2510247 s. Its outer exit0 has missing execution/native/cleanup confirmations, which remain UNKNOWN. 9593 has 36 / 2 / 34 / 3 high / known cost 447.3582925 s, with real outer execution and cleanup confirmed. Its sequence contains 21 normal acquisition, one pairing and two availability probes. This is not proof of useful discrepancy learning or scientific superiority.
- `current-two-arm-figures`: completed 9593 learned and random, sharing a code version. Random is bound to `artifacts/full-policy-random-6fc49921be` and its real outer receipt plus stdout. These two panels are descriptive only; one synthetic world does not establish comparative advantage or independent statistical N.
- No uncertainty-run file has been read. Once its terminal receipt is available, create a **new** explicit three-arm manifest and a new output directory. Do not overwrite either existing plot or rewrite earlier evidence.

## Verification

34 control cases passed (`validation-72e8aa95/command.json`, native exit0). They cover meaningful malformed identities, counts and budgets, UNKNOWN labels, missing costs, old unconfirmed receipts, forbidden paths, hash mismatch, output preservation, exact comparison stdout, duplicate runs, and one-to-three arms. Test values are artificial and never inserted into real data.

The actual historical/two-version render passed in `validation-aa7df04f`; current same-source two-arm render passed in `current-validation-c84a95fd`. The first test run failed on a test reader's implicit GBK decoding after 30 other controls passed; `validation-6fbaf17e` and `test_figures_v1.py` preserve it. Only the test reader was changed to explicit UTF-8; figure code/output were not weakened.

The historical SVG was rasterized through the already bundled `sharp` only for QA (`preview-validation-*`, exit0). It was visually inspected: both timelines, all 36 labels, legends, code/protocol text and cost bars are legible. Initial viewer/PowerShell access errors were resolved by a byte-identical Python copy to `qa-visible.png`, without ACL changes. The renderer itself does not require sharp, PIL or any new package. The same-source figure uses the same layout and passed the actual renderer; it has not separately been visually adjudicated.

R01, A03 and release remain incomplete. No active experiment, source/config/experiment file or task status was modified. The bounded test runner is a trusted-process control, not a hostile-code sandbox.
