"""External data ingestion (blueprint Phase 15).

- ``sources``: curated source registry + idempotent registry sync.
- ``ingest``: staged-file import engine (raw staging, validation, missing
  value handling, dedup/quarantine, run bookkeeping) with the WARM factor
  adapter and a generic tabular material-flow adapter.
"""
