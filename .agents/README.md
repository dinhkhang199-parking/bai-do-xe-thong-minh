# Context for ITS Parking maintenance

Read `../ARCHITECTURE.md`, `../docs/BUSINESS_RULES.md`, and the relevant MODULE.md before changing behavior.

Scope: third-year software project; hardware simulators are intentional. Do not claim real-device connectivity or an academic grade. The SPA is in `frontend/web`; Streamlit-named auth functions remain compatibility names only.

Provider/model is runtime configuration (`ITS_OPENAI_VISION_MODEL`); do not replace it with a model hard-coded in a document. Preserve current credentials and data. Never copy live .env, banking configuration, photos or DBs into test workspaces or commits. Do not initiate a bank login as a regression test.

Accuracy is not format validity. Preserve B/8 identity. Uncertain, multiple or disagreeing plates must reach human review. Keep owner/image binding and frontend response guards.

Run `python scripts/isolated_checks.py --coverage` for full regressions, and `python scripts/demo_acceptance.py --output work/demo-acceptance.json` for real HTTP against a disposable offline demo. The clean Windows dependency lock is `requirements/windows-py314.lock.txt`. Use `docs/REQUIREMENTS_TRACEABILITY.md` for evidence, not an old test count.

The Multica development mirror is a separate snapshot. Applying a reviewed change to this source does not update that mirror automatically. Record source hashes and contributions honestly; never fabricate development history.
