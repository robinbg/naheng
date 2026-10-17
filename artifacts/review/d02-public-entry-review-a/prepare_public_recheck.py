from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OUT=ROOT/'artifacts/review/d02-public-entry-review-b';OUT.mkdir(exist_ok=True)
text=(HERE/'calibrate_guards.py').read_text(encoding='utf-8')
text=text.replace("STAGE/'runtime/public_capacity_session.py'","ROOT/'src/naheng/runtime/public_capacity_session.py'")
text=text.replace("candidate_returned_phase_exit","public_returned_phase_exit")
text=text.replace("'mode':'pure_saved_report_and_AST_exit_projection_calibration'","'mode':'public_source_recheck_same32_saved_report_and_AST_cases'")
(OUT/'calibrate_guards.py').write_text(text,encoding='utf-8')
(OUT/'run_review.py').write_bytes((HERE/'run_review.py').read_bytes())
print(str(OUT))
