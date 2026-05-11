"""Generate the architecture diagram (PNG) as a deliverable.

Uses matplotlib only - no graphviz dependency - so it renders identically
on any machine that can run the pipeline. The layout is a left-to-right
five-lane medallion architecture; each lane is a column with stacked boxes.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt

from utils import ANNEX_ROOT


COLORS = {
    "source":        "#FDE2C4",
    "ingest":        "#FFD79B",
    "transform":     "#9ECAE1",
    "store":         "#A1D99B",
    "consume":       "#C5B0D5",
    "observability": "#F0BBBC",
}


def box(ax, x, y, w, h, label, fill, *, lw=1.4, fs=9.5):
    rect = patches.FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.04,rounding_size=0.18",
        linewidth=lw, edgecolor="#333", facecolor=fill,
    )
    ax.add_patch(rect)
    ax.text(x + w / 2, y + h / 2, label,
            ha="center", va="center", fontsize=fs, wrap=True)


def harrow(ax, x1, x2, y, *, color="#444", label=None):
    ax.annotate(
        "",
        xy=(x2, y), xytext=(x1, y),
        arrowprops=dict(arrowstyle="->,head_length=8,head_width=6",
                        color=color, linewidth=1.4),
    )
    if label:
        ax.text((x1 + x2) / 2, y + 0.15, label,
                ha="center", va="bottom", fontsize=8, color=color, style="italic")


def lane_title(ax, x, y, text):
    ax.text(x, y, text, ha="center", va="bottom", weight="bold",
            color="#444", fontsize=10)


def render(out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(17, 9.5))
    ax.set_xlim(0, 20)
    ax.set_ylim(0, 11)
    ax.axis("off")
    ax.set_title("ABC Phones - Credit Portfolio Data Pipeline (Medallion Architecture)",
                 fontsize=15, weight="bold", pad=20)

    # Lane x ranges:  SOURCE 0-3.4 | INGEST 4.0-7.0 | TRANSFORM 7.6-12.0 | STORE 12.6-15.6 | CONSUME 16.2-19.5
    lane_title(ax, 1.7,  10.0, "1. SOURCE\n(Bronze)")
    lane_title(ax, 5.5,  10.0, "2. INGEST")
    lane_title(ax, 9.8,  10.0, "3. TRANSFORM\n(Silver / Gold)")
    lane_title(ax, 14.1, 10.0, "4. STORE")
    lane_title(ax, 17.8, 10.0, "5. CONSUME")

    # ---- 1. Source ----
    box(ax, 0.2, 7.6, 3.4, 1.5,
        "Credit Snapshots\n5x CSV by snapshot date", COLORS["source"])
    box(ax, 0.2, 5.5, 3.4, 1.5,
        "Sales & Customer\nExcel - 4 sheets", COLORS["source"])
    box(ax, 0.2, 3.4, 3.4, 1.5,
        "NPS Survey\nExcel", COLORS["source"])

    # ---- 2. Ingest ----
    box(ax, 4.0, 4.4, 3.2, 4.2,
        "Python ingestion\n\n - filename-stamped\n   snapshot dates\n - schema-drift defence\n - Excel blank-row strip\n - mixed-format date parser\n - structured JSONL log",
        COLORS["ingest"])

    # ---- 3. Transform ----
    box(ax, 7.6, 7.4, 4.4, 1.7,
        "Cleaning\nsnake_case headers - dedupe by\nprimary key - type coercion", COLORS["transform"])
    box(ax, 7.6, 5.2, 4.4, 1.7,
        "Feature Engineering\nage_band - income_band -\ndays_past_due - risk_category", COLORS["transform"])
    box(ax, 7.6, 3.0, 4.4, 1.7,
        "Data Quality (7 checks)\nfreshness - uniqueness - RI -\nranges - nulls - schema drift", COLORS["transform"])

    # ---- 4. Store ----
    box(ax, 12.6, 4.4, 3.0, 4.2,
        "DuckDB Warehouse\nMIT - file-based\n\nTables\n  fct_portfolio_snapshot\n  dim_customer\n  fct_sales\n  fct_nps\n\nViews\n  v_portfolio_health\n  v_portfolio_by_*\n  v_credit_x_nps",
        COLORS["store"], fs=9)

    # ---- 5. Consume ----
    box(ax, 16.2, 7.4, 3.6, 1.7,
        "Analyst SQL\nDuckDB CLI / BI tool of\nchoice (Tableau / Metabase)", COLORS["consume"])
    box(ax, 16.2, 5.2, 3.6, 1.7,
        "Outputs\nportfolio_metrics.csv,\ndq_results.json, charts/", COLORS["consume"])
    box(ax, 16.2, 3.0, 3.6, 1.7,
        "Slide Deck (PDF)\nregenerated each run -\nartifacts pinned to outputs/", COLORS["consume"])

    # ---- Cross-cutting: Observability & error handling (bottom row) ----
    box(ax, 0.2, 1.0, 13.8, 1.3,
        "Observability  -  logs/pipeline-*.jsonl (structured per stage)  |  "
        "DQ alerts -> email / Slack / PagerDuty via dispatch_alert()  |  "
        "idempotent writes, per-stage exit codes",
        COLORS["observability"], fs=9.5)
    box(ax, 14.4, 1.0, 5.4, 1.3,
        "Error handling\n - quarantine bad rows in outputs/dq_*.csv\n - retry on transient I/O failures\n - alert above severity threshold",
        COLORS["observability"], fs=9)

    # ---- Connectors: source -> ingest ----
    harrow(ax, 3.6, 4.0, 8.3)
    harrow(ax, 3.6, 4.0, 6.2)
    harrow(ax, 3.6, 4.0, 4.1)

    # ---- ingest -> transform (one bus into each transform box) ----
    harrow(ax, 7.2, 7.6, 8.2, label="Parquet")
    harrow(ax, 7.2, 7.6, 6.0)
    harrow(ax, 7.2, 7.6, 3.8)

    # ---- transform -> store ----
    harrow(ax, 12.0, 12.6, 8.2)
    harrow(ax, 12.0, 12.6, 6.0)
    harrow(ax, 12.0, 12.6, 3.8)

    # ---- store -> consume ----
    harrow(ax, 15.6, 16.2, 8.2, label="SQL")
    harrow(ax, 15.6, 16.2, 6.0)
    harrow(ax, 15.6, 16.2, 3.8)

    # Legend along bottom
    legend = [
        ("Source", COLORS["source"]),
        ("Ingest", COLORS["ingest"]),
        ("Transform", COLORS["transform"]),
        ("Store", COLORS["store"]),
        ("Consume", COLORS["consume"]),
        ("Observability", COLORS["observability"]),
    ]
    for i, (label, color) in enumerate(legend):
        rect = patches.FancyBboxPatch(
            (0.5 + i * 3.2, 0.1), 0.5, 0.4,
            boxstyle="round,pad=0.02,rounding_size=0.1",
            linewidth=1.0, edgecolor="#444", facecolor=color,
        )
        ax.add_patch(rect)
        ax.text(1.1 + i * 3.2, 0.3, label, va="center", ha="left", fontsize=9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    out = ANNEX_ROOT / "pipeline_design" / "architecture.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    render(out)
    print(f"OK  architecture -> {out}")
