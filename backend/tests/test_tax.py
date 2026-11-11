"""Tax engine validation.

Every expected value below was calculated by hand from the published rate
schedules (IRS Rev. Proc. 2024-40 for 2025, Rev. Proc. 2025-32 for 2026) and
the statutory formulas, independently of the code under test. The arithmetic
is shown in the comments.
"""
import numpy as np
import pytest

from app.engine.rmd import rmd_fraction, rmd_start_age, uniform_lifetime_divisor
from app.engine.social_security import claim_factor, full_retirement_age_months, spousal_factor
from app.engine.tax import (
    bracket_tax,
    federal_income_tax,
    irmaa_monthly,
    payroll_tax,
    state_income_tax,
    taxable_social_security,
)
from app.engine.taxrules import available_years, load_rules, rules_for


def arr(x):
    return np.array([float(x)])


def P(year, status, **kw):
    return load_rules(year).params(year, status, **kw)


def fed(p, ordinary=0, qdiv=0, ltcg=0, ss=0, n65=0):
    return federal_income_tax(p, ordinary_income=arr(ordinary), qualified_dividends=arr(qdiv),
                              long_term_gains=arr(ltcg), ss_benefits=arr(ss),
                              net_investment_income=arr(qdiv + ltcg), n_age_65=n65)


class TestBrackets:
    def test_2025_single_100k(self):
        # 10% x 11,925 = 1,192.50; 12% x 36,550 = 4,386.00; 22% x 51,525 = 11,335.50
        p = P(2025, "single")
        assert bracket_tax(arr(100_000), p.bracket_edges, p.bracket_rates)[0] == pytest.approx(16_914.00)

    def test_2025_mfj_200k(self):
        # 2,385 + 12% x 73,100 = 8,772 + 22% x 103,050 = 22,671
        p = P(2025, "mfj")
        assert bracket_tax(arr(200_000), p.bracket_edges, p.bracket_rates)[0] == pytest.approx(33_828.00)

    def test_2026_single_60k(self):
        # 1,240 + 12% x 38,000 = 4,560 + 22% x 9,600 = 2,112
        p = P(2026, "single")
        assert bracket_tax(arr(60_000), p.bracket_edges, p.bracket_rates)[0] == pytest.approx(7_912.00)

    def test_2026_mfj_top_bracket(self):
        # 2,480 + 9,120 + 24,332 + 46,116 + 34,848 + 89,687.50 + 37% x 231,300 = 85,581
        p = P(2026, "mfj")
        assert bracket_tax(arr(1_000_000), p.bracket_edges, p.bracket_rates)[0] == pytest.approx(292_164.50)

    def test_zero_and_bracket_edges(self):
        p = P(2026, "single")
        assert bracket_tax(arr(0), p.bracket_edges, p.bracket_rates)[0] == 0
        assert bracket_tax(arr(12_400), p.bracket_edges, p.bracket_rates)[0] == pytest.approx(1_240.00)

    def test_bracket_top_lookup(self):
        p = P(2026, "mfj")
        assert p.bracket_top(0.22) == 211_400
        assert p.bracket_top(0.37) == float("inf")
        with pytest.raises(ValueError):
            p.bracket_top(0.5)

    def test_vectorised_matches_scalar(self):
        p = P(2026, "single")
        incomes = np.array([0, 5_000, 60_000, 300_000, 2_000_000], dtype=float)
        together = bracket_tax(incomes, p.bracket_edges, p.bracket_rates)
        one_by_one = [bracket_tax(arr(v), p.bracket_edges, p.bracket_rates)[0] for v in incomes]
        assert together == pytest.approx(one_by_one)


class TestSocialSecurityTaxation:
    def test_below_first_base_is_tax_free(self):
        # provisional = 10,000 + 10,000 = 20,000 < 25,000
        assert taxable_social_security(arr(10_000), arr(20_000), 25_000, 34_000)[0] == 0

    def test_between_bases(self):
        # provisional 30,000: min(50% x 20,000, 50% x (30,000 - 25,000)) = 2,500
        assert taxable_social_security(arr(20_000), arr(20_000), 25_000, 34_000)[0] == pytest.approx(2_500)

    def test_above_second_base(self):
        # provisional 52,000: 85% x 18,000 = 15,300 + min(12,000, 4,500) = 19,800 < 85% x 24,000 = 20,400
        assert taxable_social_security(arr(40_000), arr(24_000), 25_000, 34_000)[0] == pytest.approx(19_800)

    def test_85_percent_cap(self):
        # MFJ provisional 120,000: capped at 85% x 40,000 = 34,000
        assert taxable_social_security(arr(100_000), arr(40_000), 32_000, 44_000)[0] == pytest.approx(34_000)


class TestFederalIncomeTax:
    def test_retiree_2026_single_age_67(self):
        # pension 40,000 + SS 24,000 -> taxable SS 19,800; AGI 59,800
        # deduction 16,100 + 2,050 + 6,000 senior = 24,150; taxable income 35,650
        # tax 1,240 + 12% x 23,250 = 2,790 -> 4,030
        r = fed(P(2026, "single"), ordinary=40_000, ss=24_000, n65=1)
        assert r.taxable_ss[0] == pytest.approx(19_800)
        assert r.agi[0] == pytest.approx(59_800)
        assert r.deduction[0] == pytest.approx(24_150)
        assert r.taxable_income[0] == pytest.approx(35_650)
        assert r.total[0] == pytest.approx(4_030.00)
        assert r.marginal_rate[0] == pytest.approx(0.12)

    def test_senior_deduction_phase_out(self):
        # AGI 100,000: senior = 6,000 - 6% x 25,000 = 4,500; deduction 22,650; TI 77,350
        # tax 1,240 + 4,560 + 22% x 26,950 = 5,929 -> 11,729
        r = fed(P(2026, "single"), ordinary=100_000, n65=1)
        assert r.deduction[0] == pytest.approx(22_650)
        assert r.total[0] == pytest.approx(11_729.00)

    def test_senior_deduction_expires_after_2028(self):
        assert load_rules(2026).params(2028, "single").senior_amount == 6_000
        assert load_rules(2026).params(2029, "single").senior_amount == 0

    def test_capital_gains_use_zero_and_15_percent_bands(self):
        # 2026 single: ordinary 40,000 + LTCG 30,000; TI 53,900; ordinary TI 23,900
        # ordinary tax 1,240 + 12% x 11,500 = 2,620
        # 0% band: 49,450 - 23,900 = 25,550; 15% on 4,450 = 667.50
        r = fed(P(2026, "single"), ordinary=40_000, ltcg=30_000)
        assert r.ordinary_tax[0] == pytest.approx(2_620.00)
        assert r.ltcg_tax[0] == pytest.approx(667.50)
        assert r.niit[0] == 0

    def test_high_income_gains_and_niit(self):
        # 2026 MFJ: ordinary 600,000 + LTCG 100,000; TI 667,800; ordinary TI 567,800
        # ordinary tax 2,480+9,120+24,332+46,116+34,848+35% x 55,350 = 136,268.50
        # 15% x 45,900 + 20% x 54,100 = 17,705; NIIT 3.8% x min(100,000, 450,000) = 3,800
        r = fed(P(2026, "mfj"), ordinary=600_000, ltcg=100_000)
        assert r.ordinary_tax[0] == pytest.approx(136_268.50)
        assert r.ltcg_tax[0] == pytest.approx(17_705.00)
        assert r.niit[0] == pytest.approx(3_800.00)
        assert r.total[0] == pytest.approx(157_773.50)

    def test_gains_absorbed_by_standard_deduction(self):
        # only LTCG 10,000 -> below the standard deduction -> no tax
        r = fed(P(2026, "single"), ltcg=10_000)
        assert r.total[0] == 0

    def test_more_income_never_lowers_tax(self):
        p = P(2026, "mfj")
        incomes = np.linspace(0, 900_000, 400)
        tax = federal_income_tax(p, ordinary_income=incomes, qualified_dividends=np.full(400, 5_000.0),
                                 long_term_gains=np.full(400, 20_000.0), ss_benefits=np.full(400, 45_000.0),
                                 net_investment_income=np.full(400, 25_000.0), n_age_65=2).total
        steps = np.diff(tax)
        assert (steps >= -1e-6).all()
        assert (steps <= np.diff(incomes) * 0.999).all()  # marginal rate always below 100%


class TestPayrollAndState:
    def test_single_wages_over_wage_base(self):
        # 6.2% x 184,500 = 11,439 + 1.45% x 200,000 = 2,900
        assert payroll_tax(P(2026, "single"), [arr(200_000)])[0] == pytest.approx(14_339.00)

    def test_couple_additional_medicare(self):
        # SS 11,439 + 6,200; Medicare 2,900 + 1,450; additional 0.9% x 50,000 = 450
        assert payroll_tax(P(2026, "mfj"), [arr(200_000), arr(100_000)])[0] == pytest.approx(22_439.00)

    def test_state_tax_exclusions(self):
        kw = dict(agi=arr(80_000), taxable_ss=arr(15_000), retirement_income=arr(30_000))
        assert state_income_tax(rate=0.05, taxes_social_security=False, exempts_retirement_income=False,
                                **kw)[0] == pytest.approx(3_250)
        assert state_income_tax(rate=0.05, taxes_social_security=True, exempts_retirement_income=False,
                                **kw)[0] == pytest.approx(4_000)
        assert state_income_tax(rate=0.05, taxes_social_security=False, exempts_retirement_income=True,
                                **kw)[0] == pytest.approx(1_750)
        assert state_income_tax(rate=0.0, taxes_social_security=True, exempts_retirement_income=False,
                                **kw)[0] == 0


class TestIrmaa:
    def test_cliffs_single_2026(self):
        p = P(2026, "single")
        b, d = irmaa_monthly(p, np.array([50_000, 109_000, 109_001, 171_000, 171_001, 499_999, 500_000.0]))
        assert list(b) == pytest.approx([0, 0, 81.20, 202.90, 324.60, 446.30, 487.00])
        assert list(d) == pytest.approx([0, 0, 14.50, 37.50, 60.40, 83.30, 91.00])

    def test_mfj_2026(self):
        b, d = irmaa_monthly(P(2026, "mfj"), arr(300_000))
        assert (b[0], d[0]) == pytest.approx((202.90, 37.50))

    def test_2025_premium(self):
        assert P(2025, "single").part_b_monthly == pytest.approx(185.00)
        assert P(2026, "single").part_b_monthly == pytest.approx(202.90)


class TestIndexing:
    def test_indexed_and_fixed_amounts(self):
        p = load_rules(2026).params(2027, "single", index_factor=1.025, medical_index_factor=1.05)
        assert p.standard_deduction == pytest.approx(16_100 * 1.025)
        assert p.bracket_edges[1] == pytest.approx(12_400 * 1.025)
        assert p.ltcg_0_top == pytest.approx(49_450 * 1.025)
        assert p.ss_wage_base == pytest.approx(184_500 * 1.025)
        assert p.part_b_monthly == pytest.approx(202.90 * 1.05)
        # not indexed by law
        assert (p.ss_base1, p.ss_base2) == (25_000, 34_000)
        assert p.niit_threshold == 200_000
        assert p.addl_medicare_threshold == 200_000
        assert p.irmaa_thresholds[-1] == 500_000

    def test_rule_selection(self):
        assert available_years() == (2025, 2026)
        assert rules_for(2025).tax_year == 2025
        assert rules_for(2026).tax_year == 2026
        assert rules_for(2040).tax_year == 2026
        assert rules_for(2040, requested=2025).tax_year == 2025

    def test_unsupported_status(self):
        with pytest.raises(ValueError):
            load_rules(2026).params(2026, "hoh")


class TestRmd:
    def test_irs_divisors(self):
        assert uniform_lifetime_divisor(73) == 26.5
        assert uniform_lifetime_divisor(75) == 24.6
        assert uniform_lifetime_divisor(90) == 12.2
        assert uniform_lifetime_divisor(125) == 2.0

    def test_start_ages(self):
        assert rmd_start_age(1950) == 72
        assert rmd_start_age(1951) == 73
        assert rmd_start_age(1959) == 73
        assert rmd_start_age(1960) == 75

    def test_amount(self):
        # $100,000 at age 75 -> 100,000 / 24.6 = 4,065.04
        assert 100_000 * rmd_fraction(75, 1950) == pytest.approx(4_065.04, abs=0.005)
        assert rmd_fraction(72, 1955) == 0
        assert rmd_fraction(74, 1960) == 0
        assert rmd_fraction(75, 1960) == pytest.approx(1 / 24.6)


class TestSocialSecurityClaiming:
    def test_full_retirement_age(self):
        assert full_retirement_age_months(1954) == 66 * 12
        assert full_retirement_age_months(1955) == 66 * 12 + 2
        assert full_retirement_age_months(1959) == 66 * 12 + 10
        assert full_retirement_age_months(1960) == 67 * 12
        assert full_retirement_age_months(1975) == 67 * 12

    def test_claim_factors_published_by_ssa(self):
        # SSA: FRA 67 -> 70% at 62, 86.67% at 65, 100% at 67, 124% at 70
        assert claim_factor(1960, 62 * 12) == pytest.approx(0.70)
        assert claim_factor(1960, 65 * 12) == pytest.approx(0.8667, abs=1e-4)
        assert claim_factor(1960, 67 * 12) == pytest.approx(1.0)
        assert claim_factor(1960, 70 * 12) == pytest.approx(1.24)
        # SSA: FRA 66 -> 75% at 62, 132% at 70
        assert claim_factor(1954, 62 * 12) == pytest.approx(0.75)
        assert claim_factor(1954, 70 * 12) == pytest.approx(1.32)

    def test_spousal_factor(self):
        # SSA: spousal benefit at 62 with FRA 67 is 32.5% of the worker's amount = 65% of the 50%
        assert spousal_factor(1960, 62 * 12) == pytest.approx(0.65)
        assert spousal_factor(1960, 67 * 12) == 1.0
        assert spousal_factor(1960, 70 * 12) == 1.0
