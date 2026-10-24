# Projects

One folder per project: `projects/<project_id>/r<N>.json`, a `ProjectManifest`
(`shared/manifest.py`). Loaded by `backend/projects.py`; the latest revision wins.

- **Revisions are immutable.** Every edit writes `r<N+1>`; never edit an existing file.
- **No document URLs or IDs.** `cad.doc_ref` / `cad.write_target_ref` are env var *names*
  whose values live in `~/.darwin_secrets.sh`.
- Projects onboarded through the wizard are stored under `.darwin/projects/` (gitignored)
  until someone deliberately commits one here.
- Maturity is set by the B.5 rules in `backend/projects.py`, never by hand-editing a level.

| Project | Level | Domain pack |
|---|---|---|
| `fin_reference` | 3 (4 after the P0-2 live write is recorded) | `rocket_fin` |
