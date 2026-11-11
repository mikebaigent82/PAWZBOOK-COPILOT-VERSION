"""Monte Carlo, guardrails, Roth optimizer, stress tests and look-through."""
import numpy as np
import pytest

from app.engine.lookthrough import CompositionPart, HoldingInput, analyze, asset_class_weights
from app.engine.models import Guardrails
from app.engine.montecarlo import correlation_matrix, generate_returns, run_monte_carlo
from app.engine.projection import project
from app.engine.roth import compare_withdrawal_strategies, conversion_window, optimize_roth
from app.engine.stress import CustomStress, list_historical, run_custom, run_historical, run_sequence
from tests.conftest import make_plan


class TestReturns:
    @pytest.mark.parametrize("dist", ["normal", "student_t", "laplace"])
    def test_moments_and_correlations(self, plan, dist):
        r = generate_returns(plan, 40_000, 10, seed=7, distribution=dist, df=6).reshape(-1, 6)
        mu = np.array([c.expected_return for c in plan.asset_classes])
        sd = np.array([c.volatility for c in plan.asset_classes])
        assert r.mean(axis=0) == pytest.approx(mu, abs=0.002)
        assert r.std(axis=0) == pytest.approx(sd, rel=0.03)
        assert np.corrcoef(r.T) == pytest.approx(correlation_matrix(plan), abs=0.02)

    def test_fat_tails(self, plan):
        def kurtosis(dist):
            x = generate_returns(plan, 40_000, 10, seed=3, distribution=dist, df=5)[:, :, 2].ravel()
            z = (x - x.mean()) / x.std()
            return float((z ** 4).mean())
        assert kurtosis("normal") == pytest.approx(3.0, abs=0.1)
        assert kurtosis("laplace") == pytest.approx(6.0, abs=0.6)
        assert kurtosis("student_t") > 4.5

    def test_same_seed_same_numbers(self, plan):
        a = generate_returns(plan, 50, 30, seed=42)
        b = generate_returns(plan, 50, 30, seed=42)
        c = generate_returns(plan, 50, 30, seed=43)
        assert np.array_equal(a, b)
        assert not np.array_equal(a, c)

    def test_returns_floor_and_validation(self, plan):
        assert generate_returns(plan, 2_000, 40, seed=1, distribution="student_t", df=2.5).min() >= -1.0
        with pytest.raises(ValueError):
            generate_returns(plan, 10, 5, seed=1, distribution="student_t", df=2)
        bad = make_plan(correlations={"us_stocks": {"bonds": 0.99, "cash": 0.99}, "bonds": {"cash": -0.99}})
        with pytest.raises(ValueError, match="not valid"):
            correlation_matrix(bad)


class TestMonteCarlo:
    def test_reproducible(self, plan):
        a = run_monte_carlo(plan, n_paths=300, seed=11)
        b = run_monte_carlo(make_plan(), n_paths=300, seed=11)
        assert a == b
        assert run_monte_carlo(plan, n_paths=300, seed=12)["portfolio_real"] != a["portfolio_real"]
        assert a["meta"]["seed"] == 11 and a["meta"]["plan_hash"] == plan.content_hash()

    def test_output_is_consistent(self, plan):
        out = run_monte_carlo(plan, n_paths=1000, seed=5)
        assert 0 <= out["success_probability"] <= out["essential_success_probability"] <= 1
        assert out["failed_paths"] == round((1 - out["success_probability"]) * 1000)
        n = len(out["years"])
        for key in ("portfolio_nominal", "portfolio_real", "spending_real"):
            p = out[key]
            assert all(len(p[k]) == n for k in ("p10", "p25", "p50", "p75", "p90"))
            assert all(p["p10"][i] <= p["p50"][i] <= p["p90"][i] for i in range(n))
        cum = out["cumulative_failure_probability"]
        assert all(b >= a for a, b in zip(cum, cum[1:]))
        assert cum[-1] == pytest.approx(1 - out["success_probability"], abs=1e-4)
        assert sum(out["ending_portfolio_real_histogram"]["counts"]) == 1000

    def test_zero_volatility_equals_deterministic(self, plan):
        for c in plan.asset_classes:
            c.volatility = 0.0
        mc = run_monte_carlo(plan, n_paths=20, seed=1)
        det = project(plan)
        assert mc["portfolio_nominal"]["p50"] == pytest.approx([r["portfolio"] for r in det["rows"]], abs=0.01)
        assert mc["portfolio_nominal"]["p10"] == mc["portfolio_nominal"]["p90"]

    def test_more_spending_lowers_success(self, plan):
        rich = make_plan()
        rich.expenses[0].amount = 40_000
        poor = make_plan()
        poor.expenses[0].amount = 110_000
        assert (run_monte_carlo(rich, 500, 9)["success_probability"]
                > run_monte_carlo(plan, 500, 9)["success_probability"]
                > run_monte_carlo(poor, 500, 9)["success_probability"])

    def test_guardrails_improve_success(self, plan):
        plan.expenses[0].amount = 80_000
        plan.expenses[1].amount = 30_000
        base = run_monte_carlo(plan, 1000, 21)
        guarded = plan.model_copy(deep=True)
        guarded.assumptions.guardrails = Guardrails(enabled=True, max_multiplier=1.0)
        g = run_monte_carlo(guarded, 1000, 21)
        assert g["success_probability"] > base["success_probability"]
        assert g["guardrails"]["paths_with_a_cut"] > 0
        assert base["guardrails"]["paths_with_a_cut"] == 0
        assert g["guardrails"]["paths_with_a_raise"] == 0


class TestRothOptimizer:
    def test_candidates_and_recommendation(self, plan):
        out = optimize_roth(plan)
        keys = {c["key"] for c in out["candidates"]}
        assert "none" in keys and "fill_22_gap" in keys and "irmaa_gap" in keys and "fill_12_now" in keys
        assert out["recommended_key"] in keys
        none = next(c for c in out["candidates"] if c["key"] == "none")
        assert none["metrics"]["total_converted_nominal"] == 0
        assert none["vs_baseline"] == {"lifetime_cost": 0, "after_tax_wealth": 0, "beneficiary_value": 0}
        best = out["candidates"][0]
        assert best["score"] == max(c["score"] for c in out["candidates"])
        assert any(c["pareto_efficient"] for c in out["candidates"])
        assert out["window"] == conversion_window(plan) == (2028, 2036)

    def test_matches_direct_projection(self, plan):
        out = optimize_roth(plan)
        cand = next(c for c in out["candidates"] if c["key"] == "fill_22_gap")
        direct = plan.model_copy(deep=True)
        direct.assumptions.roth_conversion = type(direct.assumptions.roth_conversion)(**cand["conversion"])
        summary = project(direct)["summary"]
        assert cand["metrics"]["lifetime_taxes_real"] == summary["lifetime_taxes_real"]
        assert sum(cand["conversions_by_year"]) == pytest.approx(summary["total_roth_conversions_nominal"], abs=0.5)

    def test_weights_change_ranking_inputs(self, plan):
        tax_only = optimize_roth(plan, {"lifetime_cost": 1, "after_tax_wealth": 0, "beneficiary_value": 0})
        best = tax_only["candidates"][0]
        assert best["metrics"]["lifetime_cost"] == min(c["metrics"]["lifetime_cost"] for c in tax_only["candidates"])

    def test_no_pretax_money_means_nothing_to_convert(self):
        p = make_plan()
        p.accounts = [a for a in p.accounts if a.tax_type != "traditional"]
        out = optimize_roth(p)
        assert [c["key"] for c in out["candidates"]] == ["none"]
        assert out["recommended_key"] == "none"

    def test_withdrawal_strategy_comparison(self, plan):
        out = compare_withdrawal_strategies(plan)
        assert {c["key"] for c in out["candidates"]} == {"taxable_first", "traditional_first", "roth_first",
                                                         "proportional"}
        assert sum(c["current"] for c in out["candidates"]) == 1


class TestStress:
    def test_historical_catalogue_is_labelled(self):
        items = list_historical()
        assert {i["key"] for i in items} >= {"financial_crisis_2008", "dotcom_2000", "stagflation_1973"}
        assert all("HISTORICAL" in i["data_note"] for i in items)

    def test_2008_replay(self, plan):
        out = run_historical(plan, "financial_crisis_2008")
        assert out["start_year"] == 2029  # first year both are retired
        assert out["applied"][0]["historical_year"] == 2008 and out["applied"][0]["equity"] == -0.37
        t = 2029 - 2026
        assert out["stressed_rows"][t]["portfolio"] < out["baseline_rows"][t]["portfolio"]
        assert out["stressed_rows"][t - 1] == out["baseline_rows"][t - 1]
        assert out["stressed_summary"]["ending_portfolio_real"] < out["baseline_summary"]["ending_portfolio_real"]
        assert "not a prediction" in out["label"]
        with pytest.raises(ValueError):
            run_historical(plan, "nope")

    def test_stagflation_changes_inflation(self, plan):
        out = run_historical(plan, "stagflation_1973", start_year=2030)
        t = 2031 - 2026
        assert out["price_index"][t] == pytest.approx(out["baseline_price_index"][t] / 1.025 * 1.087, rel=1e-6)

    def test_custom_stress(self, plan):
        out = run_custom(plan, CustomStress(equity_return=-0.4, duration_years=2, inflation=0.08,
                                            inflation_years=3, return_reduction=0.01, extra_years_of_life=5))
        assert len(out["applied"]) == 3
        assert out["years"][-1] == plan.end_year + 5
        assert out["stressed_summary"]["ending_portfolio_real"] < out["baseline_summary"]["ending_portfolio_real"]

    def test_sequence_risk_order_matters(self, plan):
        bad = run_sequence(plan, years=5, order="bad_first")
        good = run_sequence(plan, years=5, order="good_first")
        assert (bad["stressed_summary"]["ending_portfolio_real"]
                < bad["baseline_summary"]["ending_portfolio_real"]
                < good["stressed_summary"]["ending_portfolio_real"])
        assert len(bad["applied"]) == 10


class TestLookThrough:
    def holdings(self):
        return [
            HoldingInput(account_id="1", account_name="IRA", tax_type="traditional", symbol="BAL", name="Balanced fund",
                         value=100_000, asset_class="other", is_fund=True, composition=[
                             CompositionPart(kind="asset_class", key="us_stocks", weight=0.6),
                             CompositionPart(kind="asset_class", key="bonds", weight=0.4),
                             CompositionPart(kind="security", key="ACME", name="Acme Corp", weight=0.10),
                             CompositionPart(kind="sector", key="tech", name="Technology", weight=0.3)]),
            HoldingInput(account_id="2", account_name="Brokerage", tax_type="taxable", symbol="ACME",
                         name="Acme Corp", value=40_000, asset_class="us_stocks"),
            HoldingInput(account_id="2", account_name="Brokerage", tax_type="taxable", symbol="MYST",
                         name="Mystery fund", value=60_000, asset_class="intl_stocks", is_fund=True),
        ]

    def test_exposures_add_up(self):
        out = analyze(self.holdings(), {"us_stocks": "US stocks"})
        assert out["total_value"] == 200_000
        by_class = {r["key"]: r["value"] for r in out["by_asset_class"]}
        assert by_class == {"us_stocks": 100_000, "bonds": 40_000, "intl_stocks": 60_000}
        assert sum(r["share"] for r in out["by_asset_class"]) == pytest.approx(1.0)
        assert {r["key"]: r["value"] for r in out["by_tax_type"]} == {"traditional": 100_000, "taxable": 100_000}

    def test_look_through_combines_direct_and_fund_exposure(self):
        out = analyze(self.holdings())
        acme = next(p for p in out["positions"] if p["key"] == "ACME")
        assert acme["direct"] == 40_000 and acme["through_funds"] == 10_000
        assert acme["share"] == pytest.approx(0.25)
        assert any(f["code"] == "single_position" and "Acme" in f["message"] for f in out["concentration"]["flags"])
        assert out["look_through"]["covered_value"] == 100_000
        assert out["look_through"]["not_covered"] == [{"symbol": "MYST", "name": "Mystery fund", "value": 60_000}]
        assert sum(p["value"] for p in out["positions"]) == pytest.approx(200_000)

    def test_account_weights(self):
        w = asset_class_weights(self.holdings()[:1])
        assert w == pytest.approx({"us_stocks": 0.6, "bonds": 0.4})
        assert asset_class_weights([]) == {}
        assert analyze([])["total_value"] == 0
