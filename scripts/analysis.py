"""Portfolio analysis (Part 3 of the case study).

Produces:
  outputs/portfolio_metrics.csv         - snapshot-level KPI matrix (3A)
  outputs/portfolio_by_age_band.csv     - delinquency by age band (3A drill-down)
  outputs/portfolio_by_income_band.csv  - delinquency by income band (3A drill-down)
  outputs/credit_x_nps.csv              - per-respondent NPS x credit join (3B)
  outputs/nps_by_dpd_bucket.csv         - NPS distribution by DPD bucket (3B)
  outputs/charts/*.png                  - publication-ready charts
  outputs/insights.md                   - narrative answers to 3A/3B/3C

The script reads from the DuckDB warehouse so SQL views and Python share
exactly the same source of truth.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from utils import (
    ensure_dirs,
    get_logger,
    load_config,
    log_event,
    resolve_paths,
    timed,
    write_csv,
)


CHARTS_DIR_NAME = "charts"


# ---------------------------------------------------------------------------
# 3A. Portfolio Health
# ---------------------------------------------------------------------------
# Run the 3A portfolio-health queries and write CSV outputs.
def q3a_portfolio_health(con: duckdb.DuckDBPyConnection, paths) -> dict[str, pd.DataFrame]:
    # Pull KPI matrices from the warehouse views.
    metrics = con.execute("SELECT * FROM v_portfolio_health").fetchdf()
    by_age   = con.execute("SELECT * FROM v_portfolio_by_age_band").fetchdf()
    by_inc   = con.execute("SELECT * FROM v_portfolio_by_income_band").fetchdf()
    by_risk  = con.execute("SELECT * FROM v_portfolio_by_risk").fetchdf()

    # Persist each as a CSV for the outputs folder.
    write_csv(metrics, paths.outputs / "portfolio_metrics.csv")
    write_csv(by_age,  paths.outputs / "portfolio_by_age_band.csv")
    write_csv(by_inc,  paths.outputs / "portfolio_by_income_band.csv")
    write_csv(by_risk, paths.outputs / "portfolio_by_risk.csv")

    return {"metrics": metrics, "by_age": by_age, "by_inc": by_inc, "by_risk": by_risk}


# ---------------------------------------------------------------------------
# 3B. Credit x NPS
# ---------------------------------------------------------------------------
# Run the 3B credit-x-NPS queries and write CSV outputs.
def q3b_credit_x_nps(con: duckdb.DuckDBPyConnection, paths) -> dict[str, pd.DataFrame]:
    # Per-respondent credit + NPS join.
    cxn = con.execute("SELECT * FROM v_credit_x_nps").fetchdf()
    write_csv(cxn, paths.outputs / "credit_x_nps.csv")

    # NPS metrics aggregated by days-past-due bucket.
    by_dpd = con.execute(
        """
        SELECT
            CASE
                WHEN days_past_due IS NULL THEN 'no_match'
                WHEN days_past_due = 0     THEN '0 (current)'
                WHEN days_past_due BETWEEN 1 AND 7   THEN '1-7'
                WHEN days_past_due BETWEEN 8 AND 30  THEN '8-30'
                WHEN days_past_due BETWEEN 31 AND 60 THEN '31-60'
                WHEN days_past_due BETWEEN 61 AND 90 THEN '61-90'
                ELSE '90+'
            END AS dpd_bucket,
            COUNT(*)                         AS respondents,
            AVG(nps_score)                   AS avg_nps,
            AVG((nps_score >= 9)::INT)       AS promoter_rate,
            AVG((nps_score <= 6)::INT)       AS detractor_rate
        FROM v_credit_x_nps
        WHERE nps_score IS NOT NULL
        GROUP BY 1
        ORDER BY CASE dpd_bucket
                    WHEN 'no_match'    THEN 99
                    WHEN '0 (current)' THEN 0
                    WHEN '1-7'         THEN 1
                    WHEN '8-30'        THEN 2
                    WHEN '31-60'       THEN 3
                    WHEN '61-90'       THEN 4
                    ELSE 5 END
        """
    ).fetchdf()
    write_csv(by_dpd, paths.outputs / "nps_by_dpd_bucket.csv")

    # NPS metrics aggregated by risk_category.
    by_risk = con.execute(
        """
        SELECT
            COALESCE(risk_category, 'Unknown') AS risk_category,
            COUNT(*)                          AS respondents,
            AVG(nps_score)                    AS avg_nps,
            AVG((nps_score >= 9)::INT)        AS promoter_rate,
            AVG((nps_score <= 6)::INT)        AS detractor_rate
        FROM v_credit_x_nps
        WHERE nps_score IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchdf()
    write_csv(by_risk, paths.outputs / "nps_by_risk.csv")

    return {"cxn": cxn, "by_dpd": by_dpd, "by_risk": by_risk}


# ---------------------------------------------------------------------------
# Charts (matplotlib only, no styling overrides for repeatability)
# ---------------------------------------------------------------------------
# Line chart of portfolio KPIs (delinquency/PAR30/write-off/paid-off) over time.
def chart_portfolio_trend(metrics: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    m = metrics.copy()
    m["snapshot_date"] = pd.to_datetime(m["snapshot_date"])
    # Plot one line per KPI as a percentage.
    for col, label in [
        ("delinquency_rate", "Delinquency"),
        ("par30_rate", "PAR 30"),
        ("write_off_rate", "Write Off"),
        ("paid_off_rate", "Paid Off"),
    ]:
        ax.plot(m["snapshot_date"], m[col] * 100, marker="o", label=label)
    ax.set_title("Portfolio KPIs by Snapshot")
    ax.set_ylabel("% of accounts")
    ax.set_xlabel("Snapshot")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# Bar chart of delinquency rate by age band, grouped by snapshot.
def chart_dpd_by_age(by_age: pd.DataFrame, out: Path) -> None:
    df = by_age.dropna(subset=["age_band"])
    df = df[df["age_band"] != "Unknown"]
    if df.empty:
        return
    # Pivot to age_band x snapshot for grouped bars.
    pivot = df.pivot_table(index="age_band", columns="snapshot_date",
                           values="delinquency_rate", aggfunc="mean")
    fig, ax = plt.subplots(figsize=(9, 5))
    pivot.mul(100).plot(kind="bar", ax=ax)
    ax.set_title("Delinquency Rate by Age Band & Snapshot")
    ax.set_ylabel("% delinquent")
    ax.set_xlabel("Age band")
    ax.legend(title="Snapshot", bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# Bar chart of delinquency rate by income band, in income order.
def chart_dpd_by_income(by_inc: pd.DataFrame, out: Path) -> None:
    # Force income bands to display in ascending order.
    order = [
        "Below 5,000", "5,000-9,999", "10,000-19,999", "20,000-29,999",
        "30,000-49,999", "50,000-99,999", "100,000-149,999", "150,000+",
    ]
    df = by_inc[by_inc["income_band"].isin(order)].copy()
    df["income_band"] = pd.Categorical(df["income_band"], categories=order, ordered=True)
    if df.empty:
        return
    pivot = df.pivot_table(index="income_band", columns="snapshot_date",
                           values="delinquency_rate", aggfunc="mean", observed=False)
    fig, ax = plt.subplots(figsize=(10, 5))
    pivot.mul(100).plot(kind="bar", ax=ax)
    ax.set_title("Delinquency Rate by Monthly Income Band")
    ax.set_ylabel("% delinquent")
    ax.set_xlabel("Income band (KES / month)")
    ax.legend(title="Snapshot", bbox_to_anchor=(1.02, 1), loc="upper left")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# Bar chart of average NPS score per days-past-due bucket.
def chart_nps_by_dpd(by_dpd: pd.DataFrame, out: Path) -> None:
    df = by_dpd[by_dpd["dpd_bucket"] != "no_match"].copy()
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(df["dpd_bucket"], df["avg_nps"], color="#4c72b0")
    ax.set_title("Average NPS by Days-Past-Due Bucket")
    ax.set_ylabel("Mean NPS score (0-10)")
    ax.set_xlabel("Days past due at survey time")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# Stacked-bar chart showing risk-category mix as % of accounts per snapshot.
def chart_risk_mix(by_risk: pd.DataFrame, out: Path) -> None:
    # Pivot snapshot_date x risk_category, fill missing with 0.
    pivot = by_risk.pivot_table(index="snapshot_date", columns="risk_category",
                                values="accounts", aggfunc="sum").fillna(0)
    # Reorder categories from worst-to-best for visual stacking.
    cols_order = [c for c in ["Critical", "High", "Medium", "Low"] if c in pivot.columns]
    pivot = pivot[cols_order]
    # Convert to percentages.
    pivot_pct = pivot.div(pivot.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(9, 5))
    pivot_pct.plot(kind="bar", stacked=True, ax=ax, colormap="RdYlGn_r")
    ax.set_title("Risk Category Mix by Snapshot")
    ax.set_ylabel("% of accounts")
    ax.set_xlabel("Snapshot")
    ax.legend(title="Risk")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Narrative (3A / 3B / 3C answer in markdown - read into slides too)
# ---------------------------------------------------------------------------
# Compute the headline statistics used in the narrative summary.
def derive_insights(metrics: pd.DataFrame, by_age: pd.DataFrame,
                    by_inc: pd.DataFrame, by_dpd: pd.DataFrame,
                    by_risk: pd.DataFrame) -> dict[str, Any]:
    """Compute the headline numbers used in narrative + slides."""

    # First and last snapshot rows for trend comparison.
    first = metrics.iloc[0]
    last = metrics.iloc[-1]

    # Mean delinquency by age band, sorted worst-first.
    age = by_age[~by_age["age_band"].isin(["Unknown"])]
    worst_age = (
        age.groupby("age_band")["delinquency_rate"].mean().sort_values(ascending=False)
        if not age.empty else pd.Series(dtype=float)
    )

    # Mean delinquency by income band, sorted worst-first.
    inc = by_inc[~by_inc["income_band"].isin(["Unknown"])]
    worst_inc = (
        inc.groupby("income_band")["delinquency_rate"].mean().sort_values(ascending=False)
        if not inc.empty else pd.Series(dtype=float)
    )

    # Compare mean NPS for current vs delinquent respondents.
    cur = by_dpd[by_dpd["dpd_bucket"] == "0 (current)"]
    del_ = by_dpd[by_dpd["dpd_bucket"].isin(["31-60", "61-90", "90+"])]
    cur_nps = float(cur["avg_nps"].mean()) if not cur.empty else float("nan")
    del_nps = float(del_["avg_nps"].mean()) if not del_.empty else float("nan")

    return {
        "first": first, "last": last,
        "worst_age": worst_age, "worst_inc": worst_inc,
        "cur_nps": cur_nps, "del_nps": del_nps,
        "by_risk_last": by_risk[by_risk["snapshot_date"] == by_risk["snapshot_date"].max()],
    }


# Build the narrative Markdown file from the derived insights.
def write_insights_md(out_path: Path, ins: dict[str, Any], by_dpd: pd.DataFrame) -> None:
    # Unpack the precomputed numbers.
    first, last = ins["first"], ins["last"]
    worst_age = ins["worst_age"]
    worst_inc = ins["worst_inc"]
    by_risk_last = ins["by_risk_last"]

    lines: list[str] = []
    # 3A: portfolio health KPIs + stressed segments.
    lines += [
        "# Portfolio Insights",
        "",
        "## 3A. Portfolio Health",
        "",
        "**Headline KPIs (first vs last snapshot):**",
        "",
        f"- Delinquency: {first['delinquency_rate']:.1%} -> {last['delinquency_rate']:.1%}",
        f"- PAR 30: {first['par30_rate']:.1%} -> {last['par30_rate']:.1%}",
        f"- Write Off: {first['write_off_rate']:.1%} -> {last['write_off_rate']:.1%}",
        f"- Paid Off: {first['paid_off_rate']:.1%} -> {last['paid_off_rate']:.1%}",
        f"- Collection rate: {first['collection_rate']:.1%} -> {last['collection_rate']:.1%}",
        "",
        "**Most-stressed customer segments (mean delinquency across snapshots):**",
        "",
    ]
    # Top-3 worst age bands.
    if not worst_age.empty:
        lines.append("- Age band:")
        for label, val in worst_age.head(3).items():
            lines.append(f"  - `{label}` -> {val:.1%}")
    # Top-3 worst income bands.
    if not worst_inc.empty:
        lines.append("- Income band:")
        for label, val in worst_inc.head(3).items():
            lines.append(f"  - `{label}` -> {val:.1%}")

    # Risk mix for the most recent snapshot.
    lines += ["", "**Latest snapshot risk mix:**", ""]
    for _, row in by_risk_last.iterrows():
        lines.append(f"- {row['risk_category']}: {int(row['accounts']):,} accounts | balance KES {row['balance']:,.0f}")

    # 3B: credit outcomes x customer experience.
    lines += [
        "",
        "## 3B. Credit Outcomes x Customer Experience",
        "",
        f"- Mean NPS for *current* respondents: **{ins['cur_nps']:.2f}**",
        f"- Mean NPS for respondents at PAR 30+: **{ins['del_nps']:.2f}**",
        f"- Spread = **{(ins['cur_nps'] - ins['del_nps']):.2f}** NPS points.",
        "",
        "### NPS by Days-Past-Due bucket",
        "",
        "| DPD bucket | Respondents | Avg NPS | Promoter % | Detractor % |",
        "|------------|-------------|---------|------------|-------------|",
    ]
    # Render one table row per DPD bucket.
    for _, row in by_dpd.iterrows():
        lines.append(
            f"| {row['dpd_bucket']} | {int(row['respondents']):,} | "
            f"{row['avg_nps']:.2f} | {row['promoter_rate']:.1%} | {row['detractor_rate']:.1%} |"
        )

    # 3C: data gaps + recommended improvements.
    lines += [
        "",
        "**Recommendation.** Customers experiencing payment friction report lower NPS. "
        "Decoupling collections messaging from product satisfaction surveys, and routing "
        "PAR 7-30 accounts to a low-friction self-service repayment flow (MoApp) before "
        "involving a human collector, should lift CX and recover cash sooner.",
        "",
        "## 3C. Data Gaps & Improvements",
        "",
        "**Missing.** No employment-type column, no location/region, no per-transaction ledger "
        "(only balances), no device-level cost or financing margin.",
        "",
        "**Inconsistent.** Date formats vary across files (`mm/dd/yyyy` in credit CSVs, ISO+TZ in "
        "DOB), schema drift between credit snapshots (later snapshots add an `Unnamed: 28` column), "
        "and Excel sheets pad to ~1M rows with blanks.",
        "",
        "**Ambiguous.** `CUSTOMER_AGE` in the credit CSV is actually days-since-sale, not the "
        "customer's age; the `ACCOUNT_STATUS_L1` taxonomy mixes lifecycle stages with delinquency "
        "buckets (e.g. `First Month Default without inventory 08-14`).",
        "",
        "**Proposed improvements.**",
        "1. Move sales / DOB / income / NPS to a transactional system that emits JSON events to "
        "Kafka (or polled hourly via Airbyte) instead of Excel sheets - eliminates blank-row "
        "padding and gives an append-only audit trail.",
        "2. Add an authoritative `customer_id` foreign key (separate from `loan_id`) so multi-loan "
        "customers can be analysed at the person level.",
        "3. Normalise the account-status taxonomy to two orthogonal columns: `lifecycle_status` "
        "and `dpd_bucket`. This is what analysts already approximate via L1+L2; encoding it once "
        "at source will remove the need for downstream string parsing.",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
# CLI entrypoint: run queries, render charts, write narrative.
def main(argv: list[str] | None = None) -> int:
    # Parse CLI args.
    parser = argparse.ArgumentParser(description="Run portfolio analysis")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    # Load config + set up directories and logger.
    cfg = load_config(args.config)
    paths = resolve_paths(cfg)
    ensure_dirs(paths)
    logger = get_logger("analysis", paths.logs)

    # Ensure the charts subfolder exists.
    charts_dir = paths.outputs / CHARTS_DIR_NAME
    charts_dir.mkdir(parents=True, exist_ok=True)

    # Connect to the DuckDB warehouse.
    con = duckdb.connect(str(paths.warehouse))
    try:
        # 3A: portfolio health KPIs.
        with timed(logger, "q3a"):
            a = q3a_portfolio_health(con, paths)
        # 3B: credit x NPS analytics.
        with timed(logger, "q3b"):
            b = q3b_credit_x_nps(con, paths)
        # Render all charts.
        with timed(logger, "charts"):
            chart_portfolio_trend(a["metrics"], charts_dir / "portfolio_trend.png")
            chart_dpd_by_age(a["by_age"],     charts_dir / "delinquency_by_age.png")
            chart_dpd_by_income(a["by_inc"],  charts_dir / "delinquency_by_income.png")
            chart_risk_mix(a["by_risk"],      charts_dir / "risk_mix.png")
            chart_nps_by_dpd(b["by_dpd"],     charts_dir / "nps_by_dpd.png")
        # Write the narrative Markdown insights file.
        with timed(logger, "insights"):
            ins = derive_insights(a["metrics"], a["by_age"], a["by_inc"],
                                  b["by_dpd"], a["by_risk"])
            write_insights_md(paths.outputs / "insights.md", ins, b["by_dpd"])
    finally:
        # Always close the DuckDB connection.
        con.close()

    log_event(logger, "analysis_complete",
              chart_dir=str(charts_dir), outputs=str(paths.outputs))
    print(f"OK  analysis -> {paths.outputs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
