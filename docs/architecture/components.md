# Component reference

| Component | Module | Key types |
|---|---|---|
| Configuration | `ca_ztcf/config.py` | `Settings`, `load_settings`, `config_hash` |
| Clock | `ca_ztcf/clock.py` | `Clock`, `SystemClock`, `FrozenClock` |
| Errors | `ca_ztcf/errors.py` | `CaZtcfError` and subclasses, each with a stable `code` |
| Device identity | `ca_ztcf/identity/` | `DeviceIdentity`, `DeviceStatus`, `DeviceIdentityRegistry` |
| Proof-of-possession | `ca_ztcf/identity/proof.py` | `NonceIssuer`, `ProofVerifier`, `PoPResult` |
| Collector base | `ca_ztcf/collectors/base.py` | `AccessDomain`, `SourceMode`, `AccessBinding`, `BindingStore`, `BaseCollector` |
| 5G collector | `ca_ztcf/collectors/nr.py` | `NRCollector`, `NrAccessEvent`, `SyntheticFixtureProvider` |
| WLAN collector | `ca_ztcf/collectors/wlan.py` | `WLANCollector`, `WlanAccessEvent` |
| Transition collector | `ca_ztcf/collectors/transition.py` | `TransitionCollector`, `TransitionEvent`, `TransitionContext` |
| Fixtures | `ca_ztcf/collectors/fixtures.py` | `FixtureProfile`, event builders |
| Evidence model | `ca_ztcf/evidence/models.py` | `EvidenceRecord`, `EvidenceItem`, `EvidenceCategory`, `ValidationStatus` |
| Assembler | `ca_ztcf/evidence/assembler.py` | `EvidenceAssembler`, `AssemblerInputs`, `evaluate_posture` |
| Freshness | `ca_ztcf/evidence/freshness.py` | `is_fresh`, `age_seconds`, `freshness_status` |
| Counters | `ca_ztcf/evidence/counters.py` | `SecurityCounters` |
| Predicates | `ca_ztcf/evidence/predicates.py` | `PredicateEvaluator`, `PredicateId`, `PredicateResult`, `PredicateVector` |
| Trust states | `ca_ztcf/trust_engine/states.py` | `TrustState`, `StateDefinition`, `STATE_DEFINITIONS` |
| Trust engine | `ca_ztcf/trust_engine/engine.py` | `TrustEngine`, `TrustRule`, `RULES`, `TrustStateManager` |
| Evaluation trace | `ca_ztcf/trust_engine/decision_trace.py` | `TrustEvaluation` |
| Policy models | `ca_ztcf/policy/models.py` | `PolicyAction`, `AccessScope`, `Decision` |
| Policy matrix | `ca_ztcf/policy/matrix.py` | `PolicyMatrix`, `MatrixEntry`, `MatrixOutcome` |
| Policy evaluator | `ca_ztcf/policy/evaluator.py` | `PolicyEvaluator` |
| Enforcement | `ca_ztcf/enforcement/` | `PolicyEnforcementPoint`, `MemoryPEP`, `topic_matches` |
| Telemetry | `ca_ztcf/telemetry/` | `configure_logging`, `Metrics`, `AuditWriter`, `redact` |
| Strategies | `ca_ztcf/strategies/` | `DecisionStrategy`, `CAZTCFStrategy`, `IndependentAuthenticationStrategy`, `StaticContinuityStrategy` |
| API | `ca_ztcf/api/` | `create_app`, `AppState`, `build_app_state` |

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness |
| GET | `/readyz` | Readiness, including a check that the policy matrix is total |
| GET | `/version` | Service, package and evidence-schema versions |
| GET | `/config/hash` | The configuration hash recorded on every decision |
| GET | `/metrics` | Prometheus exposition |
| POST | `/v1/devices` | Enrol a device (administrative; outside the access path) |
| GET | `/v1/devices/{device_id}` | Fetch an identity (public key only) |
| POST | `/v1/devices/{device_id}/status` | Change administrative status |
| POST | `/v1/devices/{device_id}/nonce` | Issue a single-use proof-of-possession nonce |
| POST | `/v1/collectors/events` | Ingest a normalised access-domain event |
| GET | `/v1/collectors/bindings` | List current access bindings |
| POST | `/v1/transitions` | Report an observation and obtain the derived transition context |
| POST | `/v1/evidence/evaluate` | Assemble evidence, evaluate predicates, derive a trust state |
| POST | `/v1/decisions/evaluate` | Produce and enforce a decision under a selected strategy |

The API never accepts or returns private key material. Asserted by
`test_no_endpoint_ever_returns_private_key_material` and `test_api_rejects_private_key_material`.
