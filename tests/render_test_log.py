"""Render TEST_LOG.md (spec 25 format) from pytest's JUnit XML: python tests/render_test_log.py"""
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = {  # test function -> (Test ID, requirement, input, expected)
    "test_T01_staging_rows_equal_file_rows": ("T-01", "FR-001", "Raw CSV", "Staging rows equal file rows (1,048,567)"),
    "test_T02_date_parsing_and_placeholders": ("T-02", "FR-003", "Date strings incl. 1/1/1800, 31/2/16, nan", "Valid dates parsed; invalid -> NULL; placeholder flagged"),
    "test_T03_placeholder_and_future_dob_give_null_age": ("T-03", "FR-007/008", "DOB 1/1/1800, future DOB", "Age NULL; no age outside 18-90"),
    "test_T04_non_positive_amounts_rejected_with_reason": ("T-04", "FR-009", "Rows with amount <= 0", "Rejected with reason"),
    "test_T05_transaction_id_unique": ("T-05", "FR-011", "Duplicate TransactionID", "One row kept"),
    "test_T06_single_transaction_customer_features": ("T-06", "FR-017", "Customers with 1 txn", "Volatility NULL; count 1; evidence Low"),
    "test_T07_features_match_hand_calculation": ("T-07", "FR-017", "5 customers", "Features equal hand calculation"),
    "test_T08_rfm_ties_get_equal_scores": ("T-08", "FR-018", "Ties in value", "Scores 1-5; ties share a score"),
    "test_T09_zero_balance_scaling_has_no_nan": ("T-09", "FR-024", "Zero / missing balance", "log1p handles; no NaN"),
    "test_T10_fixed_seed_rerun_gives_same_labels": ("T-10", "FR-026", "Fixed seed re-run", "Same labels (ARI = 1)"),
    "test_T11_weight_sensitivity_reported": ("T-11", "FR-030/031", "Weights +-10 pts", "Rank overlap reported (>= 80%)"),
    "test_T12_dashboard_total_customers_equals_sql": ("T-12", "FR-034", "Total Customers (dashboard data)", "Equals SQL distinct count"),
    "test_T13_single_city_slice_matches_sql": ("T-13", "FR-034", "Slice to one city (MUMBAI)", "Matches SQL for that city"),
    "test_T14_excel_extract_totals_equal_sql": ("T-14", "FR-036", "Excel SUMIFS source totals", "Equal SQL totals"),
    "test_T15_end_to_end_reconciliation": ("T-15", "FR-038", "End-to-end totals", "Variance 0"),
    "test_T16_unknown_city_excluded_from_rank_included_in_totals": ("T-16", "Edge", "City = UNKNOWN", "Excluded from rank; included in totals"),
    "test_waterfall_reconciles": ("Extra", "FR-012", "Row waterfall", "Raw - rejected = clean"),
    "test_scores_in_range": ("Extra", "FR-019/020", "Scores", "Within 0-100"),
    "test_segments_valid": ("Extra", "FR-027/028", "Segments", "5 named segments, each >= 3%"),
    "test_fit_rule_near_miss": ("Extra", "Spec 13.3", "Synthetic percentiles", "Fit 1 / 0.5 / 0"),
    "test_mask_id": ("Extra", "Spec 26", "C5841053", "C5***053"),
    "test_tiers_follow_design": ("Extra", "FR-030", "Tier shares", "5 / 15 / 30 / 50 %"),
    "test_dq_thresholds_met_or_documented": ("Extra", "FR-039", "DQ scorecard", "Only documented exception DQ-04"),
}


def main():
    tree = ET.parse(ROOT / "outputs" / "test_results.xml")
    rows = []
    for tc in tree.iter("testcase"):
        name = tc.get("name")
        failed = tc.find("failure") is not None or tc.find("error") is not None
        tid, req, inp, exp = SPEC.get(name, ("Extra", "", name, ""))
        actual = "As expected" if not failed else (tc.find("failure") or tc.find("error")).get("message", "")[:120]
        rows.append((tid, req, inp, exp, actual, "Fail" if failed else "Pass", name))
    rows.sort(key=lambda r: (r[0] == "Extra", r[0]))
    lines = [
        "# Test log (spec section 25)", "",
        f"Automated tests: `python -m pytest -v` after `python run_pipeline.py`. Last run: {datetime.now():%d %b %Y %H:%M}. "
        f"Result: **{sum(r[5] == 'Pass' for r in rows)} passed, {sum(r[5] == 'Fail' for r in rows)} failed.**", "",
        "| Test ID | Requirement | Input | Expected result | Actual result | Status | Test |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [f"| {a} | {b} | {c} | {d} | {e} | {f} | `{g}` |" for a, b, c, d, e, f, g in rows]
    lines += [
        "", "## User acceptance tests (manual)", "",
        "| Test ID | Requirement | Task for a peer | Expected result | Actual result | Status |",
        "|---|---|---|---|---|---|",
        "| T-17 | UAT | Open the dashboard (Manager action), find the top 5 customers in one city and say why | Done within 2 minutes without help | *(fill in)* | Not run |",
        "| T-18 | UAT | Read the Manager action page | Can state who, why, what, where, how large | *(fill in)* | Not run |",
        "",
    ]
    (ROOT / "TEST_LOG.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote TEST_LOG.md")


if __name__ == "__main__":
    main()
