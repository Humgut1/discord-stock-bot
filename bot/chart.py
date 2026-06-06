import io
import discord
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch


def make_chart(candles: list, title: str) -> discord.File:
    """캔들 리스트 → discord.File 이미지"""
    if not candles:
        raise ValueError("캔들 데이터 없음")

    opens  = [float(c["openPrice"])  for c in candles]
    closes = [float(c["closePrice"]) for c in candles]
    highs  = [float(c["highPrice"])  for c in candles]
    lows   = [float(c["lowPrice"])   for c in candles]

    fig, ax = plt.subplots(figsize=(8, 3))
    fig.patch.set_facecolor("#1a1b1e")
    ax.set_facecolor("#1a1b1e")

    for i, (o, c, h, l) in enumerate(zip(opens, closes, highs, lows)):
        color = "#57f287" if c >= o else "#ed4245"
        ax.plot([i, i], [l, h], color=color, linewidth=0.8)
        ax.add_patch(mpatches.Rectangle(
            (i - 0.3, min(o, c)), 0.6, abs(c - o) or 0.1,
            color=color, zorder=3
        ))

    ax.tick_params(colors="#949ba4", labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor("#2e3035")
    ax.set_xlim(-1, len(candles))
    ax.set_title(title, color="#dbdee1", fontsize=10, pad=6)
    plt.tight_layout(pad=0.5)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return discord.File(buf, filename="chart.png")
