import numpy as np
import pandas as pd
import re
import warnings
warnings.filterwarnings("ignore")

from sklearn.feature_extraction.text import (
    TfidfVectorizer, CountVectorizer)
from sklearn.decomposition import (
    LatentDirichletAllocation, NMF)


def extract_topics(texts, n_words=8):
    if not texts or len(texts) < 10:
        return {"available": False,
                "reason": "Need at least 10 text samples"}

    clean = []
    for t in texts:
        t = str(t).lower()
        t = re.sub(r"[^a-zA-Z\s]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) > 10:
            clean.append(t)

    if len(clean) < 10:
        return {"available": False,
                "reason": "Not enough valid text"}

    if len(clean) < 30:
        n_topics = 3
    elif len(clean) < 100:
        n_topics = 4
    else:
        n_topics = 5

    results = {}

    # LDA
    try:
        vec_lda = CountVectorizer(
            max_features=500,
            stop_words="english",
            min_df=1,
            max_df=0.95,
        )
        dtm   = vec_lda.fit_transform(clean)
        words = vec_lda.get_feature_names_out()

        lda = LatentDirichletAllocation(
            n_components=n_topics,
            random_state=42,
            max_iter=20,
            learning_method="online",
        )
        lda.fit(dtm)

        lda_topics = []
        for i, comp in enumerate(lda.components_):
            top_idx   = comp.argsort()[-n_words:][::-1]
            top_words = [words[j] for j in top_idx]
            weight    = round(float(comp[top_idx].mean()), 2)
            lda_topics.append({
                "id":     i + 1,
                "label":  auto_label(top_words),
                "words":  top_words,
                "weight": weight,
            })
        results["lda"] = {
            "method": "LDA",
            "topics": lda_topics,
        }
    except Exception as e:
        results["lda"] = {"error": str(e)}

    # NMF
    try:
        vec_nmf = TfidfVectorizer(
            max_features=500,
            stop_words="english",
            min_df=1,
            max_df=0.95,
        )
        tfidf     = vec_nmf.fit_transform(clean)
        words_nmf = vec_nmf.get_feature_names_out()

        nmf = NMF(
            n_components=n_topics,
            random_state=42,
            max_iter=200,
        )
        nmf.fit(tfidf)

        nmf_topics = []
        for i, comp in enumerate(nmf.components_):
            top_idx   = comp.argsort()[-n_words:][::-1]
            top_words = [words_nmf[j] for j in top_idx]
            weight    = round(float(comp[top_idx].mean()), 3)
            nmf_topics.append({
                "id":     i + 1,
                "label":  auto_label(top_words),
                "words":  top_words,
                "weight": weight,
            })
        results["nmf"] = {
            "method": "NMF",
            "topics": nmf_topics,
        }
    except Exception as e:
        results["nmf"] = {"error": str(e)}

    # Document topic distribution
    doc_topics = []
    try:
        vec2 = CountVectorizer(
            max_features=500,
            stop_words="english",
            min_df=1,
        )
        dtm2     = vec2.fit_transform(clean)
        lda2     = LatentDirichletAllocation(
            n_components=n_topics, random_state=42,
            max_iter=20)
        doc_dist = lda2.fit_transform(dtm2)
        dominant = doc_dist.argmax(axis=1)
        counts   = pd.Series(dominant).value_counts()

        best_topics = results.get("lda",{}).get("topics",[])
        for tid, cnt in counts.items():
            if tid < len(best_topics):
                label = best_topics[tid]["label"]
            else:
                label = f"Topic {tid+1}"
            doc_topics.append({
                "topic": label,
                "count": int(cnt),
                "pct":   round(cnt/len(clean)*100, 1),
            })
    except Exception:
        pass

    # Keyword frequency
    keyword_freq = []
    try:
        vec_kf = TfidfVectorizer(
            max_features=30,
            stop_words="english",
            ngram_range=(1, 2),
        )
        tfidf_kf = vec_kf.fit_transform(clean)
        scores   = np.asarray(
            tfidf_kf.mean(axis=0)).flatten()
        kwords   = vec_kf.get_feature_names_out()
        top_idx  = scores.argsort()[-20:][::-1]
        keyword_freq = [
            {"word":  kwords[i],
             "score": round(float(scores[i])*100, 1)}
            for i in top_idx
        ]
    except Exception:
        pass

    best_method = "lda"
    if ("lda" in results and
            "topics" in results.get("lda", {})):
        best_method = "lda"
    elif ("nmf" in results and
            "topics" in results.get("nmf", {})):
        best_method = "nmf"

    best_topics = results.get(
        best_method, {}).get("topics", [])

    return {
        "available":    True,
        "n_topics":     n_topics,
        "n_texts":      len(clean),
        "best_method":  best_method.upper(),
        "topics":       best_topics,
        "lda_topics":   results.get("lda",{}).get("topics",[]),
        "nmf_topics":   results.get("nmf",{}).get("topics",[]),
        "doc_topics":   doc_topics,
        "keyword_freq": keyword_freq,
    }


def auto_label(words):
    word_set = set(words[:5])
    label_map = {
        "Quality":     {"quality","good","great","excellent",
                        "best","perfect","amazing"},
        "Delivery":    {"delivery","shipping","arrived","fast",
                        "days","package","received"},
        "Value":       {"price","money","worth","cheap",
                        "expensive","value","cost"},
        "Service":     {"service","customer","support","help",
                        "response","staff","team"},
        "Product":     {"product","item","bought","purchase",
                        "ordered","buy","recommend"},
        "Experience":  {"experience","use","using","easy",
                        "comfortable","works","feel"},
        "Performance": {"performance","fast","slow","speed",
                        "power","strong","effective"},
        "Design":      {"design","look","style","color",
                        "beautiful","nice","appearance"},
        "Durability":  {"durable","lasted","broke","quality",
                        "material","built","sturdy"},
        "Food":        {"taste","flavor","delicious","fresh",
                        "food","eat","good"},
    }
    best_label = None
    best_score = 0
    for label, keywords in label_map.items():
        score = len(word_set & keywords)
        if score > best_score:
            best_score = score
            best_label = label
    return best_label if best_label else "General"