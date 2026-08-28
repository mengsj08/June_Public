# Reproducibility and verification

The synthetic demo is deterministic for a fixed date and requires no network or third-party Python packages.

```bash
python3 scripts/doctor.py
python3 scripts/run_demo.py --date 2026-01-15 --output-dir /tmp/sih-a
python3 scripts/run_demo.py --date 2026-01-15 --output-dir /tmp/sih-b
diff -ru /tmp/sih-a /tmp/sih-b
python3 -m unittest discover -s tests -v
```

The committed fixture uses fictional names, records, URLs, and identifiers. `example.org` URLs are documentation placeholders and should not be interpreted as upstream claims.

Live adapters are best-effort integrations whose upstream schemas and rate limits can change. A successful offline demo proves the pipeline contract; it does not prove that every external service is currently reachable. Run live checks separately and retain the generated manifests as local evidence.

For a minimal PubMed + arXiv check:

```bash
PYTHONPATH=src python3 -m sih_ref.cli run \
  --config config/sources.live-smoke.json \
  --profile config/profile.example.json \
  --output-dir /tmp/sih-live-smoke \
  --live --stateless
```
