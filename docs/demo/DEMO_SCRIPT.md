# WrapCheck judge demo — 60 seconds

1. Click **Download sample delivery** and say: “This ZIP is the actual camera, production sound, reports, and measured SHA-256 manifest—not a walkthrough video.”
2. Click **Load problem delivery**. WrapCheck deterministically reports exactly two blockers.
3. Select **24B / Take 7** and play the 7-second camera clip. Its separate sound player is absent because `SR12_024B_T07.wav` never reached the delivery.
4. Point to Camera Card **A017 · 1/2 copies**. The primary hash is verified but the secondary copy is still pending, so the cards cannot be erased.
5. Mark the missing sound **Recovered** and the second-copy check **Recovered**. Enter the DIT's name; only then can the human release the cards and download the editorial report.
6. Click **Load recovered delivery**. Every camera and WAV asset now has two matching verified hashes, producing zero blockers, but named human release remains mandatory.
7. Expand **How this decision was produced**: fixture mode is labelled honestly; a live deployment shows the real ClickHouse SQL/MCP/model/tool telemetry.

If time permits, extract `problem-delivery.zip` and upload the files through **Upload your extracted delivery**. The progress indicator demonstrates the same registration, validation, normalization, hashing, persistence, and reconciliation path used in production.
