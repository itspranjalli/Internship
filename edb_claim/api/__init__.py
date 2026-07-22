"""HTTP API layer for the EDB RIS(C) claim app (FastAPI).

Thin adapter over the deterministic pipeline (``edb_claim.app.pipeline``): it
serialises results to JSON and streams analysis progress to the browser. It adds
**no** domain logic and computes **no** claim figure — every number comes from
the audited Python engine. The React frontend (``webui/``) is the only consumer.
"""
