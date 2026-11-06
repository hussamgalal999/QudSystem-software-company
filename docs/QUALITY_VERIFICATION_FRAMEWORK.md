# Qudron quality verification framework

**Purpose:** turn every backlog item into a specialty-specific, evidence-backed completion decision. This framework is deliberately stricter than "code exists" or "CI passed".

## Non-negotiable completion rule

A task is **complete and verified** only when every mandatory gate in its profile has a passing, current, traceable evidence record for the exact candidate commit and deployment target. A green unit-test workflow is one evidence type, not universal proof. Missing credentials, live provider access, physical devices, customer permissions, or production hosts are recorded as external gates; they are not silently counted as completed.

Never change a task's status to complete because:
- a file or adapter was added;
- a mock test passed;
- a health endpoint returned 200 without a real inference/action;
- a provider appears in a catalogue;
- a workflow was skipped;
- a task was submitted but not polled to terminal state;
- a dashboard or page bootstrap script exists but was not run;
- a historical repository count exists without inspecting the repositories.

## Evidence record required for each gate

Each verification record must include:
- task ID and gate ID;
- exact repository, branch and commit SHA;
- test command or live procedure and environment;
- timestamp in UTC and target region where relevant;
- outcome: pass / fail / blocked / not-run;
- artifact, workflow, trace, log or report reference;
- verifier identity (automation or human);
- limitations, sample size and expiry/retest condition.

Do not store secrets, session cookies, raw customer documents or unnecessary personal data in evidence.

## Maturity levels (not interchangeable)

| Level | Meaning | What it proves |
|---|---|---|
| M0 | Not started | No implementation evidence |
| M1 | Designed | Architecture/specification only |
| M2 | Implemented | Code exists; no adequate test proof |
| M3 | CI verified | Tests pass on an exact commit |
| M4 | Integration verified | Connected components work together in a controlled environment |
| M5 | Live verified | Real provider/device/account/host path works with authorized access |
| M6 | Operationally verified | Restart, monitoring, quotas, security, backup/restore, rollback and sustained operation pass |
| M7 | Independently accepted | Independent review and owner sign-off where the risk requires it |

A task's required final level depends on its area. Do not compare M3 code tasks with M6 production tasks as if they have the same finish line.

## Specialty-specific verification profiles

Every task in `project_task_registry.json` carries a `verification_profile`. The following gates are the minimum expected for each specialty:

### Runtime
- [ ] `functional_correctness` — اختبارات السلوك الوظيفي
- [ ] `concurrency_and_race_safety` — التزامن ومنع السباقات
- [ ] `restart_and_failure_recovery` — استعادة التشغيل بعد الأعطال
- [ ] `idempotency_and_retry_bounds` — منع التكرار وحدود إعادة المحاولة
- [ ] `security_and_authorization` — الأمان والصلاحيات
- [ ] `observability` — السجلات والقياس والتنبيهات
- [ ] `deployment_smoke_and_rollback` — اختبار النشر والتراجع

### Workforce
- [ ] `registry_schema_integrity`
- [ ] `unique_role_and_team_coverage`
- [ ] `task_to_role_routing`
- [ ] `independent_review_and_quality_gates`
- [ ] `concurrency_and_resource_limits`
- [ ] `role_memory_isolation`
- [ ] `workload_evaluation`

### Continuity
- [ ] `durable_persistence`
- [ ] `project_and_agent_scope_isolation`
- [ ] `restart_resume_recovery`
- [ ] `idempotency_and_event_order`
- [ ] `sensitive_data_redaction`
- [ ] `external_handoff_reconciliation`
- [ ] `provenance_and_audit`

### Capacity
- [ ] `admission_control`
- [ ] `fairness_and_backpressure`
- [ ] `measured_load_and_latency`
- [ ] `provider_quota_enforcement`
- [ ] `resource_and_cost_accounting`
- [ ] `failure_and_recovery_under_load`
- [ ] `scale_report_reproducibility`

### External Swarm
- [ ] `provider_contract_compatibility`
- [ ] `bounded_parallel_dispatch`
- [ ] `polling_and_timeout_handling`
- [ ] `retry_cancel_and_resume`
- [ ] `artifact_integrity_and_provenance`
- [ ] `result_aggregation_and_independent_verification`
- [ ] `quota_and_cost_limits`

### Manus
- [ ] `official_api_contracts`
- [ ] `credential_scope_and_secret_handling`
- [ ] `account_entitlement_and_quota`
- [ ] `create_poll_detail_and_followup`
- [ ] `attachment_ingestion_and_hashing`
- [ ] `restart_safe_remote_task_recovery`
- [ ] `human_approval_and_audit`

### Model Supply
- [ ] `official_model_identity` — التحقق من هوية النموذج الرسمية
- [ ] `authorized_access_and_terms`
- [ ] `live_inference_smoke` — استدلال حي ناجح
- [ ] `task_quality_benchmark` — اختبار جودة المهمة
- [ ] `latency_and_availability_measurement`
- [ ] `quota_and_cost_enforcement` — ضبط الحصص والتكلفة
- [ ] `privacy_and_data_classification`
- [ ] `fallback_and_circuit_breaker`

### Android
- [ ] `owner_device_authorization` — تفويض جهاز المالك
- [ ] `authenticated_qudron_to_artemis_path`
- [ ] `device_identity_and_capability_probe`
- [ ] `task_completion_and_trace_verification`
- [ ] `read_only_or_approved_mutation_boundary`
- [ ] `failure_recovery_and_cancellation`
- [ ] `evidence_retention_and_redaction`

### Android Security
- [ ] `written_scope_and_authorization`
- [ ] `static_and_dynamic_test_coverage`
- [ ] `permission_and_exported_component_review`
- [ ] `network_and_storage_assessment`
- [ ] `reproducible_findings_and_severity`
- [ ] `non_destructive_execution`
- [ ] `responsible_disclosure_report`

### Portfolio
- [ ] `repository_inventory_coverage` — تغطية جرد المستودعات
- [ ] `private_and_inaccessible_repo_accounting`
- [ ] `deduplication_and_provenance`
- [ ] `build_and_test_health`
- [ ] `security_license_and_secret_scan`
- [ ] `product_value_and_customer_fit`
- [ ] `owner_next_action_and_disposition`

### Growth
- [ ] `correct_brand_and_destination_binding`
- [ ] `account_permission_verification`
- [ ] `read_sync_and_analytics_freshness`
- [ ] `draft_only_write_contract`
- [ ] `explicit_publish_approval`
- [ ] `content_quality_and_policy_review`
- [ ] `audit_and_rollback`

### Communications
- [ ] `official_channel_and_identity`
- [ ] `recipient_consent_and_opt_out`
- [ ] `webhook_signature_and_replay_protection`
- [ ] `delivery_and_failure_receipts`
- [ ] `privacy_and_retention`
- [ ] `human_handoff`
- [ ] `owner_allowlist_and_abuse_controls`

### CVPen
- [ ] `tenant_isolation_and_authentication`
- [ ] `malware_and_file_validation`
- [ ] `pdf_docx_extraction_accuracy`
- [ ] `rendering_and_ats_readability`
- [ ] `human_quality_and_factuality_review`
- [ ] `payment_signature_and_idempotency`
- [ ] `retention_deletion_and_audit`
- [ ] `backup_restore_and_access_control`

### Commercial
- [ ] `consent_and_order_state_machine`
- [ ] `quote_and_price_integrity`
- [ ] `payment_provider_signature`
- [ ] `idempotent_fulfillment`
- [ ] `settlement_and_reconciliation`
- [ ] `delivery_acceptance_evidence`
- [ ] `margin_and_cost_reporting`

### Infrastructure
- [ ] `least_privilege_deployment`
- [ ] `secret_and_network_security`
- [ ] `persistent_storage_and_migrations`
- [ ] `health_and_dependency_checks`
- [ ] `encrypted_backup_and_restore_drill`
- [ ] `monitoring_and_alerting`
- [ ] `rollback_and_disaster_recovery`

### Governance
- [ ] `threat_model_and_risk_register`
- [ ] `approval_enforcement_at_tool_boundary`
- [ ] `audit_trail_and_actor_attribution`
- [ ] `critical_high_vulnerability_closure`
- [ ] `data_privacy_and_retention`
- [ ] `rollback_and_incident_response`
- [ ] `owner_risk_acceptance`

### Product Engineering
- [ ] `input_rights_and_source_provenance`
- [ ] `design_fidelity_measurement`
- [ ] `generated_code_quality`
- [ ] `automated_build_and_tests`
- [ ] `visual_regression_and_accessibility`
- [ ] `design_tool_export_integrity`
- [ ] `security_and_dependency_review`

### Release
- [ ] `exact_commit_ci_green`
- [ ] `dependency_and_secret_security_scan`
- [ ] `integration_and_smoke_tests`
- [ ] `independent_code_review`
- [ ] `deployment_and_health_evidence`
- [ ] `backup_and_rollback_drill`
- [ ] `release_manifest_and_signoff`

## Scoring model

For each task, evaluate each applicable gate as:
- **Pass = 1.0** only with current evidence for the exact candidate commit and target.
- **Partial = 0.5** only when the test ran and a bounded subset passed; explain the uncovered scope and sample size.
- **Fail = 0.0** when tested and failed.
- **Blocked / not run = 0.0 for coverage**, while retaining its distinct status in reporting. It is never converted into a pass.
- **Stale = 0.0** until the evidence is rerun against the current candidate commit.

### Weight assignment

1. Each task may define a `gate_weights` object keyed by the exact gate IDs in its `verification_profile`.
2. Every weight must be a positive number; weights must sum to **100** (tolerance 0.01).
3. If `gate_weights` is absent, assign equal weight to every required gate: (w_i = 100/n). Do not invent weights after seeing the results.
4. A gate not present in `verification_profile` is not scored. A gate present in the profile cannot be silently omitted.
5. Mark security, privacy, authorization, payment integrity, data-loss prevention and owner approval gates as **critical** in the task's `critical_gates` list. Critical gates are hard release blockers.

### Exact formulas

Let (s_i) be the gate score (1.0, 0.5 or 0.0) and (w_i) its weight.

[
\text{Evidence Coverage} =
\frac{\sum_{i=1}^{n} w_i s_i}{\sum_{i=1}^{n} w_i}\times 100
]

Blocked, not-run and stale gates contribute zero to the numerator and remain in the denominator. Report their counts separately so a high score cannot hide missing access or missing tests.

[
\text{Verified Completion} =
\begin{cases}
100, & \text{if every mandatory gate passes, all critical gates pass, and the required maturity level is reached}\\
0, & \text{otherwise}
\end{cases}
]

Evidence Coverage is a diagnostic progress measure; Verified Completion is the acceptance decision. They must never be merged into one percentage.

For portfolio reporting, publish counts for complete, partial, failed, blocked, not run, and stale evidence. Show the exact denominator, weight map, commit SHA, environment and evidence references. Never average away a critical security, privacy, payment, authorization or data-loss failure; any mandatory critical gate failure blocks release regardless of numeric score.

## Required release-level gates

- Exact commit CI and regression suite.
- Dependency, secret, container and static security scans.
- Integration tests for every enabled connector.
- Real inference/action test for every provider or device claimed as active.
- Least-privilege credentials, secret rotation, audit trail and approval enforcement.
- Load, quota, cost and backpressure tests at the claimed scale.
- Backup and restore drill for persistent state and artifacts.
- Monitoring, incident handling and rollback.
- Human owner approval for production, customer data, publishing, messaging, payments, account changes and physical-device mutations.

## Special rule: external blockers

Where an external credential, subscription entitlement, account permission, physical device, or host is required, Qudron must:
1. exhaust code-only and public-documentation work that does not require the missing access;
2. implement a safe adapter and mock/contract tests;
3. add a precise owner setup procedure and preflight check;
4. automatically detect whether access is available without exposing secrets;
5. run a harmless live test only after authorized access exists;
6. keep the task explicitly blocked until live evidence exists.

This prevents a missing credential from stopping unrelated work, without pretending that a live integration was completed.

## Current scope addition

The remote compute fabric is now an explicit P0 backlog task. It must unify authorized hosted GPU/CPU resources, remote Ollama endpoints, notebooks, cloud computers and browser workers behind one capability contract. The fabric must discover and qualify resources, measure actual free quota and model quality, provision on demand, persist artifacts and checkpoints, and release resources. It must not assume that a free cloud VM includes a GPU or that an Ollama endpoint is free or permanently available.
