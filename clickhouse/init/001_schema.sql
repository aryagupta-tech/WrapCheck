CREATE DATABASE IF NOT EXISTS wrapcheck;

CREATE TABLE IF NOT EXISTS wrapcheck.productions (
  production_id String,
  title String,
  created_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY production_id;

CREATE TABLE IF NOT EXISTS wrapcheck.scenes (
  production_id String,
  scene_id String,
  heading String,
  script_text String,
  created_at DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (production_id, scene_id);

CREATE TABLE IF NOT EXISTS wrapcheck.takes (
  production_id String,
  scene_id String,
  shot_id String,
  take_id String,
  role LowCardinality(String),
  asset_uri String,
  duration_ms UInt64,
  created_at DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (production_id, scene_id, shot_id, take_id);

CREATE TABLE IF NOT EXISTS wrapcheck.observations (
  observation_id String,
  production_id String,
  scene_id String,
  shot_id String,
  take_id String,
  timestamp_start_ms UInt64,
  timestamp_end_ms UInt64,
  entity_type LowCardinality(String),
  entity_name String,
  attribute LowCardinality(String),
  observed_value String,
  confidence Float32,
  evidence_description String,
  evidence_frame_timestamp_ms UInt64,
  source LowCardinality(String),
  created_at DateTime64(3, 'UTC'),
  INDEX entity_attr_bf (entity_name, attribute) TYPE bloom_filter GRANULARITY 4
) ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (production_id, scene_id, take_id, entity_type, entity_name, attribute, observation_id);

CREATE TABLE IF NOT EXISTS wrapcheck.continuity_expectations (
  expectation_id UUID DEFAULT generateUUIDv4(),
  production_id String,
  scene_id String,
  entity_name String,
  attribute String,
  expected_value String,
  source_observation_id String,
  created_at DateTime64(3, 'UTC') DEFAULT now64()
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (production_id, scene_id, entity_name, attribute);

CREATE TABLE IF NOT EXISTS wrapcheck.conflicts (
  conflict_id String,
  production_id String,
  scene_id String,
  reference_observation_id String,
  current_observation_id String,
  entity_type LowCardinality(String),
  entity_name String,
  attribute LowCardinality(String),
  reference_value String,
  current_value String,
  confidence Float32,
  severity LowCardinality(String),
  deterministic_reason String,
  created_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (production_id, scene_id, conflict_id);

CREATE TABLE IF NOT EXISTS wrapcheck.human_decisions (
  conflict_id String,
  decision LowCardinality(String),
  reviewer String,
  note String,
  created_at DateTime64(3, 'UTC')
) ENGINE = MergeTree
ORDER BY (conflict_id, created_at);

CREATE TABLE IF NOT EXISTS wrapcheck.agent_runs (
  run_id UUID DEFAULT generateUUIDv4(),
  production_id String,
  scene_id String,
  mode LowCardinality(String),
  status LowCardinality(String),
  model String,
  started_at DateTime64(3, 'UTC'),
  finished_at Nullable(DateTime64(3, 'UTC')),
  error String DEFAULT ''
) ENGINE = MergeTree
ORDER BY (production_id, scene_id, started_at);

CREATE TABLE IF NOT EXISTS wrapcheck.tool_calls (
  call_id UUID DEFAULT generateUUIDv4(),
  run_id UUID,
  step_name LowCardinality(String),
  tool_name LowCardinality(String),
  status LowCardinality(String),
  input_summary String,
  output_summary String,
  started_at DateTime64(3, 'UTC'),
  finished_at Nullable(DateTime64(3, 'UTC')),
  error String DEFAULT ''
) ENGINE = MergeTree
ORDER BY (run_id, started_at);

CREATE TABLE IF NOT EXISTS wrapcheck.scene_requirements (
  requirement_id String,
  production_id String,
  scene_id String,
  setup_id String,
  requirement_type LowCardinality(String),
  label String,
  entity_name String,
  attribute LowCardinality(String),
  expected_value String,
  created_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (production_id, scene_id, setup_id, requirement_id);

CREATE TABLE IF NOT EXISTS wrapcheck.requirement_observations (
  observation_id String,
  run_id String,
  production_id String,
  scene_id String,
  setup_id String,
  take_id String,
  requirement_id String,
  result LowCardinality(String),
  normalized_value String,
  confidence Float32,
  evidence_description String,
  timestamp_start_ms Nullable(UInt64),
  timestamp_end_ms Nullable(UInt64),
  source LowCardinality(String),
  created_at DateTime64(3, 'UTC'),
  INDEX requirement_bf requirement_id TYPE bloom_filter GRANULARITY 4
) ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (production_id, scene_id, setup_id, take_id, requirement_id, observation_id);

CREATE TABLE IF NOT EXISTS wrapcheck.wrap_checks (
  run_id String,
  production_id String,
  scene_id String,
  setup_id String,
  reference_take_id String,
  candidate_take_id String,
  mode LowCardinality(String),
  status LowCardinality(String),
  status_reason String,
  created_at DateTime64(3, 'UTC'),
  cleared_at Nullable(DateTime64(3, 'UTC')),
  cleared_by String
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (production_id, scene_id, setup_id, run_id);

CREATE TABLE IF NOT EXISTS wrapcheck.wrap_findings (
  finding_id String,
  run_id String,
  requirement_id String,
  finding_type LowCardinality(String),
  requirement_type LowCardinality(String),
  label String,
  expected_value String,
  observed_value String,
  reference_evidence String,
  candidate_evidence String,
  reference_timestamp_ms Nullable(UInt64),
  candidate_timestamp_ms Nullable(UInt64),
  inspected_start_ms UInt64,
  inspected_end_ms UInt64,
  confidence Float32,
  severity LowCardinality(String),
  recommended_action String,
  created_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (run_id, finding_id);

CREATE TABLE IF NOT EXISTS wrapcheck.finding_decisions (
  finding_id String,
  decision LowCardinality(String),
  reviewer String,
  note String,
  created_at DateTime64(3, 'UTC')
) ENGINE = MergeTree
ORDER BY (finding_id, created_at);

CREATE TABLE IF NOT EXISTS wrapcheck.wrap_clearances (
  run_id String,
  reviewer String,
  note String,
  created_at DateTime64(3, 'UTC')
) ENGINE = MergeTree
ORDER BY (run_id, created_at);

CREATE TABLE IF NOT EXISTS wrapcheck.demo_run_quota (
  session_hash String,
  run_id String,
  created_at DateTime64(3, 'UTC')
) ENGINE = MergeTree
TTL created_at + INTERVAL 1 DAY
ORDER BY (session_hash, created_at);

CREATE TABLE IF NOT EXISTS wrapcheck.media_expectations (
  expectation_id String, run_id String, production String, shoot_day String, scene String,
  take UInt16, circled Bool, camera_roll String, card_id String, video_filename String,
  sound_roll String, audio_filename String, frame_rate String, script_note String,
  created_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (run_id, scene, take);

CREATE TABLE IF NOT EXISTS wrapcheck.media_inventory (
  media_id String, run_id String, filename String, kind LowCardinality(String), roll String,
  card_id String, scene String, take UInt16, size_bytes UInt64,
  checksum_state LowCardinality(String), checksum String, created_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (run_id, kind, filename);

CREATE TABLE IF NOT EXISTS wrapcheck.handoff_runs (
  run_id String, production String, shoot_day String, delivery_name String,
  mode LowCardinality(String), status LowCardinality(String), status_reason String,
  created_at DateTime64(3, 'UTC'), released_at Nullable(DateTime64(3, 'UTC')), released_by String
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (production, shoot_day, run_id);

CREATE TABLE IF NOT EXISTS wrapcheck.handoff_findings (
  finding_id String, run_id String, issue_type LowCardinality(String), severity LowCardinality(String),
  title String, scene_take String, card_id String, expected String, observed String,
  evidence_json String, required_action String, created_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (run_id, finding_id);

CREATE TABLE IF NOT EXISTS wrapcheck.handoff_decisions (
  finding_id String, decision LowCardinality(String), reviewer String, note String,
  created_at DateTime64(3, 'UTC')
) ENGINE = MergeTree ORDER BY (finding_id, created_at);

CREATE TABLE IF NOT EXISTS wrapcheck.handoff_releases (
  run_id String, reviewer String, note String, created_at DateTime64(3, 'UTC')
) ENGINE = MergeTree ORDER BY (run_id, created_at);
