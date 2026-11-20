"""
RecoverAI command-line runner (no servers needed).

Runs the full pipeline on a CSV, stores everything in the SQLite audit database, and writes
reports to ./reports:
  reports/model_report.json        model metrics, leakage audit, feature importance
  reports/evaluation_report.json   rule-based vs ML-only vs agentic comparison
  reports/evaluation_table.csv     the comparison table
  reports/recovery_results.csv     one row per failed transaction with the agent's outcome
  reports/summary.md               human-readable summary

Examples
  python run_pipeline.py
  python run_pipeline.py --csv data/my_payments.csv --max-attempts 3
  python run_pipeline.py --no-llm          # force the rule engine even if LLM_API_KEY is set
"""
import argparse
import json
import os
import sys
import warnings

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
warnings.filterwarnings("ignore")

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

import pandas as pd  # noqa: E402

from backend.database.database import init_db, SessionLocal  # noqa: E402
from backend.database.models import RecoveryRecord, TransactionRecord  # noqa: E402
from backend.evaluation.evaluator import evaluation_table  # noqa: E402
from backend.services.pipeline_service import run_full_pipeline, resolve_dataset_file, SAMPLE_ID  # noqa: E402


def df_to_markdown(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, row in df.iterrows():
        out.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Run the RecoverAI pipeline end to end.")
    ap.add_argument("--csv", help="Path to a payments CSV (default: data/recoverai_payment_transactions_20000.csv)")
    ap.add_argument("--max-attempts", type=int, default=2, help="Recovery attempts per failed payment (default 2)")
    ap.add_argument("--no-llm", action="store_true", help="Do not call Gemini; use the deterministic rule engine")
    ap.add_argument("--no-eval", action="store_true", help="Skip the three-approach comparison")
    ap.add_argument("--out", default=os.path.join(ROOT, "reports"), help="Output folder for reports")
    args = ap.parse_args()

    init_db()
    if args.csv:
        path = os.path.abspath(args.csv)
        if not os.path.exists(path):
            sys.exit(f"CSV not found: {path}")
        ds_id, filename = "cli_" + os.path.splitext(os.path.basename(path))[0][:30], os.path.basename(path)
    else:
        ds_id, path, filename = resolve_dataset_file(SAMPLE_ID)

    print(f"\n=== RecoverAI pipeline: {filename} (max attempts {args.max_attempts}) ===")
    db = SessionLocal()
    try:
        s = run_full_pipeline(db, path, ds_id, filename, max_attempts=args.max_attempts,
                              use_llm=not args.no_llm, run_evaluation=not args.no_eval)
        os.makedirs(args.out, exist_ok=True)

        m = s["model_metrics"]
        print(f"\n[1] Model: {s['selected_model']}  (target: {s['prediction_target']})")
        print(f"    accuracy {m['accuracy']:.3f} | precision {m['precision']:.3f} | recall {m['recall']:.3f} | "
              f"F1 {m['f1_score']:.3f} | ROC-AUC {m['roc_auc']:.3f} | PR-AUC {m['pr_auc']:.3f} "
              f"(failure base rate {m['positive_rate']:.3f})")
        print("    Leakage control:", ", ".join(f"{r['column']} ({r['rule']})" for r in s["leakage_report"]) or "none")

        r = s["revenue_metrics"]
        print(f"\n[2] Agent recovery ({s['agent_mode']})")
        print(f"    failed payments {r['failed_transactions']:,} | recovered {r['recovered_transactions']:,} "
              f"({r['recovery_rate']}%) | revenue recovered {r['revenue_recovered']:,.2f} of "
              f"{r['revenue_at_risk']:,.2f} ({r['revenue_recovery_rate']}%)")
        print(f"    escalated to human review {r['escalated_transactions']} | executed attempts {r['total_attempts']:,} "
              f"| policy rejections {r['policy_rejections']}")

        with open(os.path.join(args.out, "model_report.json"), "w") as fh:
            json.dump({k: s[k] for k in ["selected_model", "prediction_target", "model_metrics", "candidate_models",
                                         "leakage_report", "leakage_mode", "features_used", "feature_importance"]},
                      fh, indent=2, default=str)

        rows = []
        for t in db.query(TransactionRecord).filter(TransactionRecord.dataset_id == ds_id,
                                                    TransactionRecord.actual_payment_status == "Failed").all():
            rec: RecoveryRecord = t.recovery
            rows.append({"transaction_id": t.transaction_id, "amount": t.amount, "failure_reason": t.actual_failure_reason,
                         "risk_level": t.risk_level, "failure_probability": t.failure_probability,
                         "final_action": rec.recommended_action, "attempts": rec.number_of_attempts,
                         "outcome": rec.recovery_status, "recovered_amount": rec.recovered_amount,
                         "decision_source": rec.decision_source, "reason": rec.agent_reasoning})
        pd.DataFrame(rows).to_csv(os.path.join(args.out, "recovery_results.csv"), index=False)

        lines = [f"# RecoverAI run summary\n", f"Dataset: {filename}  ", f"Run at: {s['run_at']}  ",
                 f"Agent mode: {s['agent_mode']}  ", f"Payment provider: {s['payment_provider']}\n",
                 "## Model (held-out test split)\n",
                 "| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | PR-AUC |", "|---|---|---|---|---|---|---|"]
        for name, cm in s["candidate_models"].items():
            mark = " (selected)" if name == s["selected_model"] else ""
            lines.append(f"| {name}{mark} | {cm['accuracy']:.3f} | {cm['precision']:.3f} | {cm['recall']:.3f} | "
                         f"{cm['f1_score']:.3f} | {cm['roc_auc']:.3f} | {cm['pr_auc']:.3f} |")
        lines += ["", "## Recovery (all failed payments)\n",
                  f"- Failed payments: {r['failed_transactions']:,}",
                  f"- Recovered: {r['recovered_transactions']:,} ({r['recovery_rate']}%)",
                  f"- Revenue recovered: {r['revenue_recovered']:,.2f} of {r['revenue_at_risk']:,.2f} "
                  f"({r['revenue_recovery_rate']}%)",
                  f"- Escalated to human review: {r['escalated_transactions']}", ""]

        if s.get("evaluation"):
            ev = s["evaluation"]
            table = evaluation_table(ev)
            table.to_csv(os.path.join(args.out, "evaluation_table.csv"), index=False)
            with open(os.path.join(args.out, "evaluation_report.json"), "w") as fh:
                json.dump(ev, fh, indent=2, default=str)
            print(f"\n[3] Approach comparison on {ev['eligible_transactions']} held-out failed payments "
                  f"(same simulator & seed, max {ev['max_attempts']} attempts)")
            with pd.option_context("display.width", 200, "display.max_columns", 20):
                print(table[["Approach", "RSR %", "RRR %", "RAC", "RDE", "PVR %", "PRR %", "ESC %"]].to_string(index=False))
            lines += ["## Approach comparison (held-out failed payments, simulated outcomes)\n",
                      df_to_markdown(table),
                      "", "RSR = recovery success rate, RRR = revenue recovery rate, RAC = attempts per transaction, "
                          "RDE = revenue per attempt, PVR = policy violation rate, PRR = policy rejection rate, "
                          "ESC = escalation rate."]

        md = "\n".join(map(str, lines))
        with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"\nTimings: {s['timings']}")
        print(f"Reports written to: {args.out}\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
