import io
import discord
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.font_manager as fm
import platform

# 한글 폰트 설정
def _set_korean_font():
    if platform.system() == "Windows":
        plt.rcParams["font.family"] = "Malgun Gothic"
    elif platform.system() == "Darwin":
        plt.rcParams["font.family"] = "AppleGothic"
    else:
        # Linux (서버 배포 시)
        plt.rcParams["font.family"] = "DejaVu Sans"
    plt.rcParams["axes.unicode_minus"] = False

_set_korean_font()


def make_chart(candles: list, title: str) -> discord.File:
    """캔들 리스트 → discord.File 이미지"""
    if not candles:
        raise ValueError("캔들 데이터 없음")

    opens  = [float(c["openPrice"])  for c in candles]
    closes = [float(c["closePrice"]) for c in candles]
    highs  = [float(c["highPrice"])  for c in candles]
    lows   = [float(c["lowPrice"])   for c in candles]
    n      = len(candles)

    fig, ax = plt.subplots(figsize=(8, 3))
    fig.patch.set_facecolor("#1e2128")
    ax.set_facecolor("#1e2128")

    # 그리드
    ax.yaxis.grid(True, color="#272a33", linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)

    # 캔들
    cw = max(0.3, 0.6 * (30 / n))
    for i, (o, c, h, l) in enumerate(zip(opens, closes, highs, lows)):
        color = "#57f287" if c >= o else "#ed4245"
        ax.plot([i, i], [l, h], color=color, linewidth=0.8, zorder=2)
        ax.add_patch(mpatches.Rectangle(
            (i - cw / 2, min(o, c)), cw, max(abs(c - o), (max(highs) - min(lows)) * 0.002),
            color=color, zorder=3
        ))

    # 현재가 점선
    last_price = closes[-1]
    ax.axhline(last_price, color="#4a4f5c", linewidth=0.8, linestyle="--", zorder=1)

    # 스타일
    ax.tick_params(colors="#5c6370", labelsize=7)
    ax.yaxis.set_tick_params(labelright=True, labelleft=False)
    ax.yaxis.tick_right()
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xlim(-1, n)
    ax.set_title(title, color="#dbdee1", fontsize=10, pad=6)

    plt.tight_layout(pad=0.5)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return discord.File(buf, filename="chart.png")
