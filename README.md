# RecoverAI v3: Agentic AI System for Automated Payment Revenue Recovery

RecoverAI predicts which payments are likely to fail, diagnoses why a payment failed, and uses an
AI agent (Google Gemini, with a deterministic rule-engine fallback) to choose a recovery action.
**Every action the agent proposes must pass a deterministic policy engine before it is executed.**
High-value or unclear cases go to a human review queue. Every prediction, proposal, policy verdict,
execution and outcome is stored in an SQLite audit trail and shown on a Streamlit dashboard.

```
CSV ─► Profile ─► Feature engineering ─► ML risk (LR / RF / GB, leakage-safe) ─► Failure diagnosis
                                                                                      │
          ┌───────────────────────────────────────────────────────────────────────────┘
          ▼
   Gemini agent PROPOSES ─► Policy engine (code) ─► APPROVED ─► Payment provider ─► Observe
          ▲                        │ REJECTED → reason fed back to agent           │ not recovered
          │                        │ ESCALATED → human review queue                │
          └──────────── re-evaluate (bounded by attempt limit) ◄───────────────────┘
                                                   │
                     SQLite audit trail ─► FastAPI ─► Streamlit dashboard
```

> **Simulation notice.** Recovery outcomes come from a probabilistic simulator. No real money moves.
> Razorpay Test Mode (optional) only creates *test* orders and payment links.

---

## 1. What is new in v3 (upgrade summary)

| Area | v2 (before) | v3 (now) |
|---|---|---|
| **Policy enforcement** | Retry limit only inside the loop | New deterministic **policy engine** (`backend/policy/`): attempt limit, RETRY cap, recovery window, amount limit, action eligibility per failure cause, no repeat of failed actions, controlled toolset. Every proposal gets APPROVED / REJECTED / ESCALATED with rule ids. |
| **Agent loop** | LLM output executed directly | LLM **proposes** → policy checks → rejection reason fed back to the agent → policy-safe fallback. Gemini call budget + circuit breaker. |
| **Human-in-the-loop** | – | **Escalation queue**: amounts above the limit (or agent request) wait for a reviewer; approve/reject from the dashboard or API. |
| **Evaluation** | – | **Rule-based vs ML-only vs Hybrid agentic** comparison on the same held-out failed payments, same simulator & seed. Metrics RSR, ASR, TRR, RRR, RAC, RDE, PVR, PRR, ESC, ER. |
| **Target leakage** | `gateway_status` / `authentication_status` were model inputs → **100 % accuracy** (they encode the outcome) | Post-outcome fields removed + **automatic leakage detector**; feature statistics fitted on the training split only. Honest metrics incl. PR-AUC. |
| **Simulator bug** | RNG re-seeded with the same value for every transaction → **3,105 of 3,105 failed payments "recovered" (100 %)** | Per-transaction deterministic draws, cause-aware success probabilities, attempt fatigue. Common random numbers make approach comparisons fair. |
| **Successful payments** | Could be "recovered" if risk was high | Never recovered (policy rule P1); flagged for monitoring only. |
| **Razorpay** | Placeholder (always simulated) | Real **Test Mode** integration (orders / payment links), refuses live keys, API-call cap, error fallback. |
| **Audit** | Attempts + trace | + every policy decision, escalation, reviewer action, provider reference, latency, stored pipeline runs and evaluation runs. |
| **Dashboard** | 6 tabs, re-ran the whole pipeline on every page load | 8 tabs incl. **Approach Comparison**, **Policy & Safety** (editable policy), **Human Review**; loads the last run instead of retraining on page load. |
| **CLI** | – | `run_pipeline.py` runs everything without servers and writes `reports/`. |
| **Tests** | 29 | **68** (policy rules, gate behaviour, leakage, simulator regression, evaluation, Razorpay guard, API flows). Tests use a temporary DB/model, never your real data. |
| **Bug fixes** | `/api/recovery/strategies` was shadowed by `/api/recovery/{id}` | Route order fixed; upload filenames sanitised; schema auto-upgrade. |

### Results on the bundled 20,000-transaction dataset (rule engine, max 2 attempts)

Model (held-out test split, target = payment fails; failure base rate 15.5 %):

| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|---|
| **Logistic Regression (selected)** | 0.595 | 0.189 | 0.488 | 0.272 | 0.553 | 0.210 |
| Random Forest | 0.675 | 0.200 | 0.366 | 0.259 | 0.561 | 0.200 |
| Gradient Boosting | 0.640 | 0.201 | 0.444 | 0.277 | 0.562 | 0.204 |

These scores are modest because the dataset carries only weak *pre-payment* signals (network, hour,
method, amount). The old 100 % came from leaked outcome columns, not from a better model.

Approach comparison (621 failed payments in the held-out split, same simulator and seed):

| Approach | RSR % | RRR % | Attempts / txn | Revenue / attempt | Policy violations % |
|---|---|---|---|---|---|
| A: Rule-based (fixed retry) | 50.24 | 50.62 | 1.652 | 28.16 | 32.36 |
| B: ML-only (risk tier) | 63.61 | 59.17 | 1.454 | 37.40 | 16.94 |
| **C: Hybrid agentic (RecoverAI)** | **73.75** | **72.58** | **1.436** | **46.44** | **0.00** |

All 3,105 failed payments: 2,308 recovered (74.3 %), $200,872.90 of $285,249.77 (70.4 %), 11 escalated.
Your numbers are reproduced by `python run_pipeline.py` (see `reports/summary.md`).

---

## 2. Quick start (Windows)

You need **Python 3.10 or newer** (developed and tested on Python 3.13).

1. Unzip the project, open the folder.
2. Double-click **`setup.bat`** (one time; creates `.venv` and installs packages, 2–5 min).
3. Double-click **`run_backend.bat`** – keep the window open. API docs: http://127.0.0.1:8000/docs
4. Double-click **`run_dashboard.bat`** – the dashboard opens at http://localhost:8501
5. In the dashboard sidebar click **🚀 Run agentic recovery pipeline** (about 15–30 s for 20,000 rows).

Same steps in PowerShell:

```powershell
cd RecoverAI
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env                 # only if .env does not exist

# terminal 1
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
# terminal 2 (activate .venv again)
streamlit run frontend\app.py
```

### macOS / Linux

```bash
./setup.sh      # once
./run.sh        # starts backend + dashboard
```

### No servers? Use the command-line runner

```bash
python run_pipeline.py                      # default dataset, max 2 attempts
python run_pipeline.py --max-attempts 3
python run_pipeline.py --csv path/to/your.csv
python run_pipeline.py --no-llm             # force the rule engine even with a Gemini key
```

It prints model metrics, recovery results and the approach comparison, and writes:
`reports/summary.md`, `reports/model_report.json`, `reports/evaluation_report.json`,
`reports/evaluation_table.csv`, `reports/recovery_results.csv`.

---

## 3. Turning on the Gemini agent (optional)

1. Create an API key at https://aistudio.google.com/apikey
2. In `.env` set `LLM_API_KEY=your_key` (model: `LLM_MODEL=gemini-2.5-flash`).
3. Restart the backend. The sidebar shows **Gemini: configured** and the *Use Gemini agent* toggle unlocks.

`LLM_MAX_CALLS_PER_RUN` (default 300) caps Gemini calls per run; after that, or after 3 consecutive
API errors, the rule engine decides. Each decision records its source: `GEMINI_AGENT`,
`RULE_BASED_FALLBACK`, `POLICY_SAFE_FALLBACK` or `HUMAN_REVIEWER`.
With Gemini enabled, the **Policy & Safety** tab shows how often the gate rejected the LLM (PRR).

## 4. Razorpay Test Mode (optional)

```ini
PAYMENT_PROVIDER=razorpay_test
RAZORPAY_KEY_ID=rzp_test_xxxxxxxx      # live keys (rzp_live_) are refused
RAZORPAY_KEY_SECRET=xxxxxxxx
RAZORPAY_MAX_API_CALLS=25
```

RETRY_PAYMENT / SWITCH_GATEWAY create a test **order**; REAUTHENTICATE / REQUEST_NEW_PAYMENT_METHOD
create a test **payment link**. The ids are stored with each attempt (visible in the explorer and in
your Razorpay Test dashboard). Because nobody pays in Test Mode, the outcome is still simulated and
labelled `outcome_source: SIMULATED`. The approach comparison always uses the simulator only.

---

## 5. The dashboard

| Tab | What you see |
|---|---|
| 📊 Overview | Revenue at risk / recovered / still at risk, failed vs recovered payments, escalations, attempts |
| ⚖️ Approach Comparison | A vs B vs C table and charts, recovery rate by failure cause, re-run with other settings |
| 🎯 Strategies | Success rate of each action per executed attempt |
| 🤖 Model & Explainability | Candidate models (incl. PR-AUC), confusion matrix, feature importance, **leakage audit** |
| 🛡️ Policy & Safety | Proposals checked / approved / rejected / escalated, rules triggered, **edit the policy** |
| 🧑‍⚖️ Human Review | Escalated cases; approve (executes the action) or reject with a note |
| ⚠️ Risk & Diagnosis | Risk tiers, failure causes, failures by payment method |
| 🔎 Transaction Explorer | Filter transactions; per-transaction factors, agent rationale, **policy decisions per attempt**, attempts, full trace |

## 6. The policy engine (`config/policy.json`)

| Rule | Default | Effect |
|---|---|---|
| P1 Not failed | – | Successful payments are never "recovered" |
| P2 Max attempts | 3 per transaction | Hard cap (the sidebar slider cannot exceed it) |
| P3 Retry cap | 2 × RETRY_PAYMENT | Mirrors card-network re-attempt limits |
| P4 Recovery window | 72 h | Sum of scheduled delays (retry 1 h, re-auth 0.25 h, new method 24 h) |
| P5 Amount limit | 1,000 | Above → **ESCALATED** to human review |
| P6 Eligibility | see file | e.g. no RETRY for *Insufficient Funds* or *Authentication Failed* |
| P7 No repeat | on | An action that already failed is not repeated |
| P8 Controlled toolset | – | Only the 4 recovery tools, NO_ACTION or ESCALATE_TO_HUMAN |

Edit in the dashboard (Policy & Safety tab), with `PUT /api/policy`, or directly in `config/policy.json`.

## 7. API (http://127.0.0.1:8000/docs)

| Method & path | Purpose |
|---|---|
| `POST /api/analyze` | Full pipeline (upload a CSV or use the sample). Params: `max_attempts`, `use_llm`, `run_evaluation` |
| `GET /api/analysis/latest` | Last pipeline summary |
| `GET /api/metrics`, `GET /api/transactions` | KPIs; filterable transaction list (`risk_level`, `payment_status`, `recovery_status`, `search`) |
| `GET /api/recovery/{id}`, `GET /api/agent/trace/{id}` | Full recovery profile / decision trace incl. policy decisions |
| `GET /api/recovery/strategies` | Per-action analytics |
| `POST /api/agent/analyze` | Run the gated agent on one transaction JSON |
| `GET/PUT /api/policy`, `POST /api/policy/check` | View / update policy; dry-run one action |
| `GET /api/policy/decisions`, `GET /api/policy/summary` | Policy audit log and statistics |
| `GET /api/escalations`, `POST /api/escalations/{id}/resolve` | Human review queue |
| `POST /api/evaluate`, `GET /api/evaluation/latest` | Rule-based vs ML-only vs agentic comparison |
| `POST /api/train`, `GET /api/model/status`, `GET /api/model/report` | Training and model report (leakage audit, feature importance) |
| `POST /api/upload`, `POST /api/predict`, `POST /api/recover` | Lower-level steps |
| `GET /api/health` | Status: Gemini configured, provider, leakage mode, active policy |

Example – one transaction:

```bash
curl -X POST "http://127.0.0.1:8000/api/agent/analyze?use_llm=false" -H "Content-Type: application/json" \
  -d '{"transaction_id":"T1","amount":120,"payment_status":"Failed","failure_reason":"Authentication Failed","risk_level":"MEDIUM"}'
```

## 8. Metric definitions

E = eligible failed payments (held-out split by default).
**RSR** recovered / |E| × 100 · **ASR** successful attempts / executed attempts × 100 ·
**TRR** recovered revenue · **RRR** TRR / amount of E × 100 · **RAC** executed attempts / |E| ·
**RDE** TRR / executed attempts · **PVR** executed actions violating policy / executed attempts × 100 ·
**PRR** rejected proposals / all proposals × 100 (agentic only) · **ESC** escalated / |E| × 100 ·
**ER** workflows with an execution error / |E| × 100.
Approaches A and B run without the gate (like conventional systems) and are audited afterwards for PVR.

## 9. Your data

Required columns: `payment_status` (Success/Failed) and `amount`. Recommended: `transaction_id`,
`payment_method`, `bank`, `transaction_hour`, `device_type`, `network_type`, `gateway`,
`gateway_status`, `authentication_status`, `retry_count`, `failure_reason`
(Gateway Timeout / Server Error / Authentication Failed / Insufficient Funds).
Common aliases (`status`, `txn_amount`, `pg`, …) are mapped automatically.
`data/generate_sample_data.py` regenerates the synthetic sample dataset.

## 10. Tests

```bash
python -m pytest -q          # 68 tests, ~10 s; uses a temporary database and model folder
```

## 11. Project structure

```
backend/
  agent/        recovery_agent.py (gated loop, Gemini budget), prompts.py, schemas.py
  policy/       policy_engine.py  (deterministic rules P1–P8)
  evaluation/   evaluator.py      (A vs B vs C, metrics)
  pipeline/     ingestion, profiling, feature_engineering, preprocessing (leakage control),
                model_training, prediction, failure_analysis, explainability,
                recovery_engine (policy-aware rules), simulator
  providers/    simulation.py, razorpay_provider.py (Test Mode), factory.py
  tools/        recovery_tools.py (controlled toolset)
  services/     pipeline_service.py (orchestration), metrics.py
  api/          analysis, agent_api, policy_api, evaluation_api, training, prediction, recovery, upload
  database/     models.py (incl. policy_decisions, escalations, pipeline_runs, evaluation_runs)
frontend/app.py         Streamlit dashboard
config/policy.json      Policy configuration
run_pipeline.py         Command-line runner
tests/                  68 tests
```

## 12. Honest limitations

- Recovery outcomes are **simulated**; they measure decision quality against a model of recovery,
  not real bank behaviour. Razorpay Test Mode verifies integration only.
- The bundled dataset is synthetic; pre-payment failure signals are weak, so the classifier is modest.
- Risk scores come from class-balanced models (relative risk, not calibrated probabilities).
- Without a Gemini key the agent is the rule engine; the comparison then measures the policy-aware
  rule playbook. Enable Gemini to measure the LLM's contribution and its policy rejection rate.
- LLM rationales are generated text; the authoritative record is the logged inputs, verdicts and outcomes.

## 13. Troubleshooting

| Problem | Fix |
|---|---|
| Dashboard says it cannot reach the backend | Start `run_backend.bat` first; check port 8000 is free |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use `setup.bat` |
| `No trained model found` from `/api/predict` | Run the pipeline once (dashboard button or `run_pipeline.py`) |
| Old database errors after upgrading | Delete `recoverai.db`; it is rebuilt automatically (old schemas are also auto-rebuilt) |
| Gemini toggle disabled | Put `LLM_API_KEY` in `.env` and restart the backend |
