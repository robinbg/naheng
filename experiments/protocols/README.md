# Frozen protocol contract

`naheng.experiments.preregistration` freezes the canonical protocol, source YAML, code and data identities. Configurations are in `configs/experiments/pilot.yaml` and `release.yaml`. Registrations are immutable and do not run experiments. Every published measurement must later bind its registration ID, suite, selected-policy freeze, independent trajectory ID and actual command receipt. Missing execution adapters or scientific prerequisites are blocked, and previously blocked registrations cannot authorize a later experiment.

Each new registration is first frozen at `artifacts/experiments/preregistrations/<protocol_id>/r<revision>`. `--out` only exports the identical registration; changing the protocol, source, state or data requires the next revision even when exporting to another directory. Existing canonical records and exports are compared against every freshly computed field and both protocol files. A recomputed self-hash cannot authorize fabricated status, results or scientific sample counts. Raw and observation bytes share one cross-role leakage check.

The earlier c implementation's private registrations remain historical evidence. The next pilot/release revisions explicitly bind their exact c predecessors; they are not promoted to experimental results or execution authority.
