# Security Policy

WrapCheck handles production-media metadata and can issue access to private media objects. Security reports are taken seriously, especially when they involve unauthorized playback, credential exposure, upload validation, release-policy bypass, or cross-delivery data access.

## Supported versions

Security fixes are applied to the latest commit on the `main` branch. This project has not published a stable versioned release yet.

| Version | Supported |
| --- | --- |
| Latest `main` | Yes |
| Older commits or forks | No |

## Reporting a vulnerability

Do not open a public issue for an unpatched vulnerability.

Use the repository's private security-advisory feature when it is available. Include:

- A concise description and affected component.
- Reproduction steps or a minimal proof of concept.
- Expected and observed behavior.
- Potential impact and required privileges.
- Any suggested mitigation.

If private advisories are not enabled, contact the maintainer privately using the contact method on the repository owner's profile. Do not send production footage, live credentials, service-account keys, or customer data. Use synthetic evidence and redact tokens, signed URLs, hostnames, and personal information.

The project aims to acknowledge a complete report within three business days and provide an initial assessment within fourteen days. Timelines may change with severity and maintainer availability. Please allow time for a fix before public disclosure.

## Security boundaries

The following properties are part of WrapCheck's intended security model:

- Gemini may normalize PDF/DOCX rows or summarize evidence, but cannot assert file existence, verify a checksum, resolve a finding, or release cards.
- Uploaded documents are untrusted data and cannot alter prompts, tool permissions, MCP access, or deterministic release rules.
- GCS objects remain private; playback and uploads use short-lived signed URLs.
- The application writer and read-only MCP service use different ClickHouse identities.
- Cloud Tasks invokes the ingestion worker through authenticated service-to-service requests.
- Final release requires a named human and is immutable after recording.
- Retried ingestion and mutation requests use idempotency keys.
- Public access is constrained with signed anonymous sessions plus per-session and global quotas.

## Production deployment checklist

Before handling non-demo data:

1. Store Google Cloud and ClickHouse credentials in Secret Manager.
2. Use separate least-privilege service accounts for the API, worker, GCS signer, and MCP reader.
3. Keep the MCP endpoint and internal ingestion endpoint non-public.
4. Grant the MCP ClickHouse user `SELECT` only.
5. Enforce TLS for ClickHouse, Cloud Run, MCP, and storage access.
6. Set private GCS uniform bucket-level access and a 24-hour lifecycle for temporary public-demo objects.
7. Restrict Cloud Run concurrency, instances, request sizes, and task retry limits.
8. Rotate `DEMO_QUOTA_SECRET` and all credentials after suspected exposure.
9. Enable Google Cloud audit logs, ClickHouse query logs, request IDs, and alerting.
10. Run dependency, container, and secret scanning before deployment.

Never place service-account JSON, `.env`, signed URLs, API tokens, database passwords, or unreleased customer media in the repository.

## In-scope vulnerability examples

- Accessing another delivery's private media or report.
- Forging or extending a signed upload/playback URL.
- Bypassing MIME, extension, file-signature, size, or archive validation.
- Causing one physical copy to be accepted as two verified destinations.
- Bypassing immutable human release or modifying a released decision.
- Escalating the read-only MCP identity to write access.
- Prompt injection that changes tool access or deterministic release policy.
- Idempotency or retry behavior that duplicates releases or decisions.
- Exposing secrets, raw document text, signed URLs, or personal data in logs.

## Out of scope

- Social engineering, phishing, denial-of-service load testing, or physical attacks.
- Reports that require using stolen credentials or accessing data without authorization.
- Automated scans without a demonstrated security impact.
- Findings that apply only to unsupported forks or intentionally insecure local fixture configuration.

## Safe-harbor expectations

Make a good-faith effort to avoid privacy violations, data destruction, service degradation, and access beyond what is necessary to demonstrate the issue. Stop testing and report immediately if you encounter real production media, credentials, or personal information.
