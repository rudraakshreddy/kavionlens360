# Test log (spec section 25)

Automated tests: `python -m pytest -v` after `python run_pipeline.py`. Last run: 03 Oct 2026 15:35. Result: **23 passed, 0 failed.**

| Test ID | Requirement | Input | Expected result | Actual result | Status | Test |
|---|---|---|---|---|---|---|
| T-01 | FR-001 | Raw CSV | Staging rows equal file rows (1,048,567) | As expected | Pass | `test_T01_staging_rows_equal_file_rows` |
| T-02 | FR-003 | Date strings incl. 1/1/1800, 31/2/16, nan | Valid dates parsed; invalid -> NULL; placeholder flagged | As expected | Pass | `test_T02_date_parsing_and_placeholders` |
| T-03 | FR-007/008 | DOB 1/1/1800, future DOB | Age NULL; no age outside 18-90 | As expected | Pass | `test_T03_placeholder_and_future_dob_give_null_age` |
| T-04 | FR-009 | Rows with amount <= 0 | Rejected with reason | As expected | Pass | `test_T04_non_positive_amounts_rejected_with_reason` |
| T-05 | FR-011 | Duplicate TransactionID | One row kept | As expected | Pass | `test_T05_transaction_id_unique` |
| T-06 | FR-017 | Customers with 1 txn | Volatility NULL; count 1; evidence Low | As expected | Pass | `test_T06_single_transaction_customer_features` |
| T-07 | FR-017 | 5 customers | Features equal hand calculation | As expected | Pass | `test_T07_features_match_hand_calculation` |
| T-08 | FR-018 | Ties in value | Scores 1-5; ties share a score | As expected | Pass | `test_T08_rfm_ties_get_equal_scores` |
| T-09 | FR-024 | Zero / missing balance | log1p handles; no NaN | As expected | Pass | `test_T09_zero_balance_scaling_has_no_nan` |
| T-10 | FR-026 | Fixed seed re-run | Same labels (ARI = 1) | As expected | Pass | `test_T10_fixed_seed_rerun_gives_same_labels` |
| T-11 | FR-030/031 | Weights +-10 pts | Rank overlap reported (>= 80%) | As expected | Pass | `test_T11_weight_sensitivity_reported` |
| T-12 | FR-034 | Total Customers (dashboard data) | Equals SQL distinct count | As expected | Pass | `test_T12_dashboard_total_customers_equals_sql` |
| T-13 | FR-034 | Slice to one city (MUMBAI) | Matches SQL for that city | As expected | Pass | `test_T13_single_city_slice_matches_sql` |
| T-14 | FR-036 | Excel SUMIFS source totals | Equal SQL totals | As expected | Pass | `test_T14_excel_extract_totals_equal_sql` |
| T-15 | FR-038 | End-to-end totals | Variance 0 | As expected | Pass | `test_T15_end_to_end_reconciliation` |
| T-16 | Edge | City = UNKNOWN | Excluded from rank; included in totals | As expected | Pass | `test_T16_unknown_city_excluded_from_rank_included_in_totals` |
| Extra | FR-012 | Row waterfall | Raw - rejected = clean | As expected | Pass | `test_waterfall_reconciles` |
| Extra | FR-019/020 | Scores | Within 0-100 | As expected | Pass | `test_scores_in_range` |
| Extra | FR-027/028 | Segments | 5 named segments, each >= 3% | As expected | Pass | `test_segments_valid` |
| Extra | Spec 13.3 | Synthetic percentiles | Fit 1 / 0.5 / 0 | As expected | Pass | `test_fit_rule_near_miss` |
| Extra | Spec 26 | C5841053 | C5***053 | As expected | Pass | `test_mask_id` |
| Extra | FR-030 | Tier shares | 5 / 15 / 30 / 50 % | As expected | Pass | `test_tiers_follow_design` |
| Extra | FR-039 | DQ scorecard | Only documented exception DQ-04 | As expected | Pass | `test_dq_thresholds_met_or_documented` |

## User acceptance tests (manual)

| Test ID | Requirement | Task for a peer | Expected result | Actual result | Status |
|---|---|---|---|---|---|
| T-17 | UAT | Open the dashboard (Manager action), find the top 5 customers in one city and say why | Done within 2 minutes without help | *(fill in)* | Not run |
| T-18 | UAT | Read the Manager action page | Can state who, why, what, where, how large | *(fill in)* | Not run |
