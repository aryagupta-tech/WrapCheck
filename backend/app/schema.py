DELIVERY_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS wrapcheck.delivery_snapshots (
      delivery_id String, payload_json String, status LowCardinality(String),
      updated_at DateTime64(3, 'UTC')) ENGINE = ReplacingMergeTree(updated_at) ORDER BY delivery_id""",
    """CREATE TABLE IF NOT EXISTS wrapcheck.delivery_assets (
      asset_id String, delivery_id String, kind LowCardinality(String), filename String,
      content_type String, size_bytes UInt64, storage_uri String, crc32c String, sha256 String,
      metadata_json String DEFAULT '{}', uploaded Bool, created_at DateTime64(3, 'UTC'), updated_at DateTime64(3, 'UTC'))
      ENGINE = ReplacingMergeTree(updated_at) ORDER BY (delivery_id, asset_id)""",
    "ALTER TABLE wrapcheck.delivery_assets ADD COLUMN IF NOT EXISTS metadata_json String DEFAULT '{}' AFTER sha256",
    """CREATE TABLE IF NOT EXISTS wrapcheck.media_copies (
      media_id String, run_id String, filename String, destination LowCardinality(String),
      checksum_algorithm LowCardinality(String), checksum String, verified Bool,
      verified_at Nullable(DateTime64(3, 'UTC')), created_at DateTime64(3, 'UTC'))
      ENGINE = ReplacingMergeTree(created_at) ORDER BY (run_id, filename, destination)""",
    """CREATE TABLE IF NOT EXISTS wrapcheck.ingestion_job_snapshots (
      job_id String, delivery_id String, idempotency_key String, payload_json String,
      status LowCardinality(String), updated_at DateTime64(3, 'UTC'))
      ENGINE = ReplacingMergeTree(updated_at) ORDER BY (delivery_id, idempotency_key, job_id)""",
    """CREATE TABLE IF NOT EXISTS wrapcheck.handoff_run_snapshots (
      run_id String, payload_json String, status LowCardinality(String),
      updated_at DateTime64(3, 'UTC')) ENGINE = ReplacingMergeTree(updated_at) ORDER BY run_id""",
    """CREATE TABLE IF NOT EXISTS wrapcheck.idempotency_records (
      scope LowCardinality(String), idempotency_key String, resource_id String,
      response_json String, created_at DateTime64(3, 'UTC'))
      ENGINE = ReplacingMergeTree(created_at) TTL created_at + INTERVAL 7 DAY
      ORDER BY (scope, idempotency_key)""",
    """CREATE TABLE IF NOT EXISTS wrapcheck.public_quota_events (
      session_hash String, event_type LowCardinality(String), resource_id String,
      created_at DateTime64(3, 'UTC')) ENGINE = MergeTree
      TTL created_at + INTERVAL 1 DAY ORDER BY (event_type, session_hash, created_at)""",
    """CREATE TABLE IF NOT EXISTS wrapcheck.request_audit (
      request_id String, method LowCardinality(String), path String, status_code UInt16,
      duration_ms UInt32, created_at DateTime64(3, 'UTC')) ENGINE = MergeTree
      TTL created_at + INTERVAL 30 DAY ORDER BY (created_at, request_id)""",
]


def ensure_delivery_schema(repository) -> None:
    for statement in DELIVERY_SCHEMA:
        repository.client.command(statement)
