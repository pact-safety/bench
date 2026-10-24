# CI security: workflows and dependency pins

## Pin-floor convention

Every dependency in `pyproject.toml` should eventually carry an upper
bound at the next major version, not just a floor. Unbounded floors
(`mcp[cli]>=1.0`) let an unrelated upstream major release get pulled
into CI and Docker the moment it's published — no code change on our
side, deploy just breaks.

This already happened once: `mcp` shipped 2.0.0 in 2026-08 and removed
`mcp.server.fastmcp`, which `app/mcp_server.py` imports. An unpinned
`>=1.0` let CI and Docker pull 2.0, breaking test collection and app
boot, and blocking every deploy until it was pinned. The fix, already
in `pyproject.toml`:

```toml
"mcp[cli]>=1.0,<2",
```

That's the worked example for the convention: `>=<known-good floor>,<<next major>`.

This PR does **not** mass-add upper bounds across `pyproject.toml` —
that's a separate, riskier change requiring its own review of what
each major bump actually breaks. This doc just states the convention
so new/changed deps follow it going forward.

## Security workflow (`.github/workflows/security.yml`)

Two jobs, both `runs-on: ubuntu-latest`, checkout pinned to
`actions/checkout@v4`:

- **gitleaks** (`gitleaks/gitleaks-action`, pinned to a version tag) —
  secret scanning. This job is allowed to fail the `security.yml`
  workflow: a real leaked secret should be loud.
- **pip-audit** — dependency CVE scan against installed packages.
  Runs with `continue-on-error: true`: a newly-disclosed CVE in an
  upstream package outside our control shouldn't turn CI red for
  something we can't immediately fix. Findings still show up in the
  step's log and as annotations.

**By design, `security.yml` cannot block a deploy.** `.github/workflows/deploy.yml`'s
`test` job is the only gate in front of `deploy` (`needs: test`).
`security.yml` is a separate workflow file, triggered independently on
`pull_request` and `push` to `main`; nothing in `deploy.yml` references
it. This split has wedged deploys before when security-style checks
were added directly to the test gate — don't reintroduce that
coupling. If a future change wants security findings to be
enforced, that enforcement belongs in branch protection (see below),
not in `deploy.yml`.

## Branch protection (operator action required)

This PR cannot enable branch protection — it's a GitHub repo setting,
not something a workflow file controls. To require the security
workflow and review before merge, the operator needs to, in the web
UI:

**Settings → Branches → Add branch protection rule** for `main`:

- Branch name pattern: `main`
- Enable **Require a pull request before merging**
  - Enable **Require approvals** (pick a count, e.g. 1)
- Enable **Require status checks to pass before merging**
  - Search for and add the `security.yml` job(s) (e.g. `gitleaks`,
    `pip-audit`) and the existing `test` job(s) from `test.yml`
  - Enable **Require branches to be up to date before merging** (optional,
    but recommended so checks run against the merged state)

None of this affects `deploy.yml`, which triggers on push to `main`
and is unrelated to PR merge requirements.
