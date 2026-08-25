# Legacy continuity fixtures

This folder contains the earlier continuity-analysis fixtures and is no longer used by the WrapCheck media-handoff demo.

The active, original production-delivery source and generated artifacts are under `fixtures/demo_delivery/`, `backend/app/demo_assets/`, and `backend/app/demo_packages/`. Regenerate them with:

```bash
bash scripts/generate_demo_delivery.sh
```

The active release gate proves delivery using report rows, object metadata, and matching hashes on two distinct destinations. Visual content is playable evidence for the operator, but it is never treated as proof that a file was copied safely.
