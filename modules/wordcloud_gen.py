import logging
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from wordcloud import WordCloud, STOPWORDS

LOGGER = logging.getLogger(__name__)
OUTPUT_DIR = os.path.join("static","outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Custom color functions
def purple_color(word, font_size, position,
                 orientation, random_state=None, **kwargs):
    colors = ["#534AB7","#7F77DD","#9B8FE8",
              "#3C3489","#AFA9EC","#6B63C7"]
    return colors[random_state.randint(0, len(colors)-1)]

def green_color(word, font_size, position,
                orientation, random_state=None, **kwargs):
    colors = ["#1D9E75","#0F6E56","#2DC98A",
              "#3BAF80","#4DC994","#0D8F6A"]
    return colors[random_state.randint(0, len(colors)-1)]

def red_color(word, font_size, position,
              orientation, random_state=None, **kwargs):
    colors = ["#E24B4A","#C73B3A","#E86A69",
              "#D44545","#F07070","#B83535"]
    return colors[random_state.randint(0, len(colors)-1)]

def generate_wordclouds(sentiment_stats):
    paths = {}
    configs = [
        ("all",      sentiment_stats.get("keywords",[]),
         purple_color, "lumiq_wc_all.png",
         "All Words"),
        ("positive", sentiment_stats.get("pos_keywords",[]),
         green_color, "lumiq_wc_pos.png",
         "Positive Words"),
        ("negative", sentiment_stats.get("neg_keywords",[]),
         red_color,  "lumiq_wc_neg.png",
         "Negative Words"),
    ]

    for key, keywords, color_fn, fname, title in configs:
        if not keywords or len(keywords) < 3:
            continue
        fig = None
        try:
            freq = {k["word"]: max(k["score"], 0.001) * 1000
                    for k in keywords}
            wc = WordCloud(
                width=900, height=400,
                background_color="white",
                max_words=60,
                prefer_horizontal=0.85,
                collocations=False,
                stopwords=STOPWORDS,
                min_font_size=12,
                max_font_size=90,
                color_func=color_fn,
                margin=10,
            ).generate_from_frequencies(freq)

            fig, ax = plt.subplots(figsize=(11, 5), dpi=110)
            ax.imshow(wc, interpolation="bilinear")
            ax.axis("off")
            ax.set_title(
                title,
                fontsize=14, fontweight="bold",
                pad=12, color="#1A1A2E")
            fig.patch.set_facecolor("white")
            plt.tight_layout(pad=0.5)

            path = os.path.join(OUTPUT_DIR, fname)
            plt.savefig(path, bbox_inches="tight",
                        facecolor="white", dpi=110)
            paths[key] = fname

        except Exception as exc:
            LOGGER.warning("WordCloud generation failed for %s: %s", key, exc)

        finally:
            if fig is not None:
                plt.close(fig)

    return paths