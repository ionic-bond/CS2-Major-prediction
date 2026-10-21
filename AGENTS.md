# Agent guide

## Project priorities

- This is a personal prediction project. Put effort into data quality, time-ordered evaluation, probability calibration, and maximizing the chance of passing Pick'Em.
- Keep the structure direct and sized to the work needed now. Add a directory, abstraction, dependency, or safeguard only when it solves a concrete current problem; name that problem when proposing it.
- Do not prebuild version directories, compatibility frameworks, extension points, or long-term infrastructure for hypothetical needs. Handle an actual incompatible change when it occurs; a small migration later is acceptable.
- Keep checks that protect collected data or prediction validity, such as atomic match writes, source semantics, cutoff handling, and reproducible inputs. Scale verification to the actual change.
- Keep current instructions concise. Archive completed investigations and execution history so they do not become mandatory reading for routine work.

## Documentation routing

- Start with [docs/Agent/README.md](docs/Agent/README.md), then read only the documents relevant to the task.
- The root README and future stage READMEs are the human-facing surface: overview, recommendations, BP summaries, matchup probability tables, and post-event results. Put commands, implementation details, research evidence, and working notes under `docs/Agent/`.
- Leave `2026_cologne/` unchanged unless the user explicitly requests changes there. Its documents and models are historical references, not the specification for Singapore.
- Keep current decisions in the data collection plan and modeling guide; keep dated experiments in `docs/Agent/research/`. Do not treat an old research report as a newer design decision.

## Repository paths and commands

- Shared code: `data/pipeline/`; entry point: `python -m data.pipeline` from the repository root.
- Data root: `data/`. The package location must not create a second `data/data/` directory or redirect the existing database/cache.
- Canonical tracked records: `data/datasets/` (source-family/month JSONL plus manifest). Use `Dataset` for analysis; `data/processed/history.sqlite3` is an ignored collector work database. Verify with `python -m data.pipeline verify-data`.
- Collector CLI commands restore missing SQLite automatically and publish committed rows to JSONL. After pulling a different data version, use `restore-db --replace` (backs up the existing database) if the baseline check rejects the old work database. Preserve LF for canonical files.
- Optional HLTV requirements: `data/pipeline/requirements-hltv.txt`.
- Existing focused checks: `python -m unittest discover -s data/pipeline/tests -v`.
- Event configuration: `2026_singapore/event.json`. Stage outputs should reference frozen dataset manifests.

## Data and model invariants

- HLTV is the planned primary source for team results and player map records; reuse the same match page. BO3 is an optional advanced-data supplement and fallback, not a mandatory duplicate crawl.
- Preserve raw provenance, source-specific IDs, rating versions, unknown values, and the distinction between series and map statistics. Cross-source duplicates are not resolved automatically.
- Validate bounded samples and cached replay before large collection work. A successful sample, or a recent latest match, does not prove that a historical window is complete.
- Optimize the probability of passing the actual event's Pick'Em rules. Confirm the event's rules, pairing constraints, scoring, roster cutoff, and map pool before applying a simulator.
- Validate new modeling assumptions with time-ordered evaluation. Do not inherit legacy KAST damping, BP optimality claims, probability conversions, or search optimality claims without evidence.
