#!/usr/bin/env python3
"""
plot_regional_trends.py
========================

Plots regional CPI index and median weekly pay over time (2002-2025),
one line per region, as two side-by-side comparison charts.
"""

import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

data_dir = Path("data")
ts = pd.read_csv(data_dir / "regional_cpi_timeseries.csv")
ts = ts.dropna(subset=["Regional_CPI_Proxy", "Median_Weekly_Pay"])

regions = sorted(ts["Region"].unique())
cmap = plt.get_cmap("tab20")
colors = {region: cmap(i / len(regions)) for i, region in enumerate(regions)}

fig, (ax_cpi, ax_pay) = plt.subplots(1, 2, figsize=(16, 7), sharex=True)

for region in regions:
    region_data = ts[ts["Region"] == region].sort_values("Year")
    ax_cpi.plot(region_data["Year"], region_data["Regional_CPI_Proxy"],
                label=region, color=colors[region], marker="o", markersize=3)
    ax_pay.plot(region_data["Year"], region_data["Median_Weekly_Pay"],
                label=region, color=colors[region], marker="o", markersize=3)

ax_cpi.set_title("Regional CPI Proxy Over Time")
ax_cpi.set_xlabel("Year")
ax_cpi.set_ylabel("CPI Proxy Index")
ax_cpi.grid(True, alpha=0.3)

ax_pay.set_title("Median Weekly Pay Over Time")
ax_pay.set_xlabel("Year")
ax_pay.set_ylabel("Median Weekly Pay (£)")
ax_pay.grid(True, alpha=0.3)

handles, labels = ax_cpi.get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=6, bbox_to_anchor=(0.5, -0.05))

fig.suptitle("UK Regional Cost-of-Living vs. Wages (2002-2025)", fontsize=14)
fig.tight_layout(rect=[0, 0.05, 1, 0.97])

output_path = data_dir / "regional_cpi_vs_pay_trends.png"
fig.savefig(output_path, dpi=150, bbox_inches="tight")
print(f"Saved chart to: {output_path}")
