import functools
import os
import pickle
import re
import time
import warnings

import numpy as np
import pandas as pd
import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

warnings.filterwarnings("ignore")

from sklearn.model_selection import (
    train_test_split, StratifiedKFold, cross_val_score)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.naive_bayes import ComplementNB
from sklearn.svm import LinearSVC
from sklearn.calibration import CalibratedClassifierCV
from sklearn.pipeline import Pipeline
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, confusion_matrix, classification_report,
    roc_auc_score)
from sklearn.preprocessing import LabelEncoder
from joblib import Parallel, delayed, Memory

CACHE_DIR = os.path.join("static", "outputs", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)
memory = Memory(CACHE_DIR, verbose=0)

for pkg in ["stopwords", "wordnet", "omw-1.4"]:
    try:
        nltk.data.find("corpora/" + pkg)
    except LookupError:
        nltk.download(pkg, quiet=True)

LEMMATIZER = WordNetLemmatizer()
VADER_INST = SentimentIntensityAnalyzer()
NEGATION   = {
    "not","no","never","neither","nor","nothing",
    "nowhere","nobody","none","hardly","barely"
}
STOP_WORDS = set(stopwords.words("english")) - NEGATION

CONTRACTIONS = {
    "won't":"will not","can't":"cannot","n't":" not",
    "i'm":"i am","i've":"i have","it's":"it is",
    "don't":"do not","doesn't":"does not",
    "didn't":"did not","isn't":"is not",
    "aren't":"are not","wasn't":"was not",
}

URL_PATTERN = re.compile(r"http\S+|www\S+|@\w+|#\w+")
REPEAT_PATTERN = re.compile(r"(.)\1{2,}")
NON_LETTER_PATTERN = re.compile(r"[^a-zA-Z\s]")
SPACE_PATTERN = re.compile(r"\s+")

_progress = {"step":0,"message":"Starting...","pct":0}


@functools.lru_cache(maxsize=1)
def _load_saved_pipeline():
    model_path = os.path.join("static", "outputs", "best_model.pkl")
    if os.path.exists(model_path):
        with open(model_path, "rb") as f:
            return pickle.load(f)
    return None

def set_progress(step, message, pct):
    _progress.update({"step":step,"message":message,"pct":pct})

def get_progress():
    return dict(_progress)

def clean_text_fast(text):
    text = str(text).lower()
    for k, v in CONTRACTIONS.items():
        text = text.replace(k, v)
    text = URL_PATTERN.sub(" ", text)
    text = REPEAT_PATTERN.sub(r"\1\1", text)
    text = NON_LETTER_PATTERN.sub(" ", text)
    text = SPACE_PATTERN.sub(" ", text).strip()
    return " ".join(
        LEMMATIZER.lemmatize(w)
        for w in text.split()
        if len(w) > 1 and (w not in STOP_WORDS or w in NEGATION)
    )

def clean_series(series):
    return series.fillna("").apply(clean_text_fast)

def vader_label_one(text):
    score = VADER_INST.polarity_scores(str(text))["compound"]
    if score >= 0.05:   return "Positive"
    elif score <= -0.05: return "Negative"
    else:               return "Neutral"

def vader_batch(texts):
    return [vader_label_one(t) for t in texts]

def textblob_label_one(text):
    score = TextBlob(str(text)).sentiment.polarity
    if score > 0.1:    return "Positive"
    elif score < -0.1: return "Negative"
    else:              return "Neutral"

def detect_text_column(df):
    best_col, best_score = None, 0
    for col in df.select_dtypes(include="object").columns:
        sample     = df[col].dropna().head(200)
        avg_len    = sample.apply(lambda x: len(str(x))).mean()
        unique_pct = sample.nunique() / max(len(sample), 1)
        score      = avg_len * unique_pct
        if avg_len > 15 and score > best_score:
            best_score, best_col = score, col
    return best_col

def extract_keywords(texts, top_n=15):
    try:
        if not texts or len(texts) < 2:
            return []
        vec = TfidfVectorizer(
            max_features=200, stop_words="english",
            ngram_range=(1, 2))
        tfidf  = vec.fit_transform(texts)
        scores = np.asarray(tfidf.mean(axis=0)).flatten()
        words  = vec.get_feature_names_out()
        top_idx = scores.argsort()[-top_n:][::-1]
        return [{"word": words[i],
                 "score": round(float(scores[i]), 4)}
                for i in top_idx]
    except Exception:
        return []

def predict_live(text):
    cleaned = clean_text_fast(text)
    vader_score = VADER_INST.polarity_scores(str(text))["compound"]
    result = {
        "vader_label":   vader_label_one(text),
        "vader_score":   round(vader_score, 3),
        "ml_label":      None,
        "ml_confidence": None,
    }
    model = _load_saved_pipeline()
    if model is None:
        return result
    try:
        label = model.predict([cleaned])[0]
        conf = None
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba([cleaned])[0]
            conf = round(float(max(proba)) * 100, 1)
        result["ml_label"] = label
        result["ml_confidence"] = conf
    except Exception:
        pass
    return result

def get_models():
    cfg = dict(max_features=5000, ngram_range=(1,2),
               sublinear_tf=True, min_df=1,
               strip_accents="unicode", stop_words="english")
    return {
        "Logistic Regression": Pipeline([
            ("tfidf", TfidfVectorizer(**cfg)),
            ("clf",   LogisticRegression(
                C=3.0, max_iter=300, solver="saga",
                random_state=42, class_weight="balanced")),
        ]),
        "SGD Classifier": Pipeline([
            ("tfidf", TfidfVectorizer(**cfg)),
            ("clf",   SGDClassifier(
                loss="modified_huber", alpha=0.0001,
                max_iter=100, random_state=42,
                class_weight="balanced",
                early_stopping=True, n_iter_no_change=5)),
        ]),
        "Complement NB": Pipeline([
            ("tfidf", TfidfVectorizer(**cfg)),
            ("clf",   ComplementNB(alpha=0.3)),
        ]),
        "Linear SVM": Pipeline([
            ("tfidf", TfidfVectorizer(**cfg)),
            ("clf",   CalibratedClassifierCV(
                LinearSVC(C=1.0, max_iter=1000,
                          random_state=42,
                          class_weight="balanced"), cv=3)),
        ]),
    }

def safe_cv_folds(total, n_classes):
    """Pick safe number of CV folds based on data size."""
    min_per_class = max(1, total // max(n_classes, 1))
    if min_per_class < 2: return None   # skip CV
    if min_per_class < 3: return 2
    if min_per_class < 5: return 3
    return 3

def train_one(name, pipe, X_tr, X_te,
              y_tr, y_te, label_order, X_full, y_full,
              n_folds):
    t0 = time.time()
    try:
        pipe.fit(X_tr, y_tr)
        y_pred = pipe.predict(X_te)

        acc  = round(accuracy_score(y_te, y_pred)*100, 1)
        prec = round(precision_score(y_te, y_pred,
               average="weighted",zero_division=0)*100, 1)
        rec  = round(recall_score(y_te, y_pred,
               average="weighted",zero_division=0)*100, 1)
        f1   = round(f1_score(y_te, y_pred,
               average="weighted",zero_division=0)*100, 1)

        cv_mean, cv_std, cv_each = None, None, []
        if n_folds and n_folds >= 2:
            try:
                skf = StratifiedKFold(
                    n_splits=n_folds, shuffle=True,
                    random_state=42)
                cv = cross_val_score(
                    pipe, X_full, y_full,
                    cv=skf, scoring="f1_weighted",
                    n_jobs=1)
                cv_mean = round(float(cv.mean())*100, 1)
                cv_std  = round(float(cv.std())*100, 2)
                cv_each = [round(s*100,1) for s in cv.tolist()]
            except Exception:
                pass

        auc = None
        try:
            if hasattr(pipe.named_steps["clf"],"predict_proba"):
                le  = LabelEncoder()
                yte = le.fit_transform(y_te)
                yp  = pipe.predict_proba(X_te)
                auc = round(roc_auc_score(
                    yte, yp, multi_class="ovr",
                    average="weighted"), 3)
        except Exception:
            pass

        cm  = confusion_matrix(y_te,y_pred,labels=label_order)
        rep = classification_report(
            y_te, y_pred, labels=label_order,
            output_dict=True, zero_division=0)
        per_class = {}
        for lbl in label_order:
            if lbl in rep:
                per_class[lbl] = {
                    "precision": round(rep[lbl]["precision"]*100,1),
                    "recall":    round(rep[lbl]["recall"]*100,1),
                    "f1":        round(rep[lbl]["f1-score"]*100,1),
                    "support":   int(rep[lbl]["support"]),
                }

        return name, {
            "accuracy":         acc,
            "precision":        prec,
            "recall":           rec,
            "f1":               f1,
            "cv_mean":          cv_mean,
            "cv_std":           cv_std,
            "cv_each_fold":     cv_each,
            "auc":              auc,
            "confusion_matrix": cm.tolist(),
            "per_class":        per_class,
            "train_time_sec":   round(time.time()-t0, 2),
            "pipeline":         pipe,
        }
    except Exception as e:
        return name, {"error": str(e)}

def run_sentiment(df):
    set_progress(1,"Detecting text column...", 5)
    text_col = detect_text_column(df)
    if text_col is None:
        return {"available": False}

    set_progress(2,"Cleaning text data...", 15)
    df = df.copy()
    df["clean_text"] = clean_series(df[text_col])
    df = df[df["clean_text"].str.len()>3].reset_index(drop=True)
    total = len(df)

    set_progress(3,"Running VADER sentiment...", 25)
    df["vader_label"] = vader_batch(df["clean_text"].tolist())

    set_progress(4,"Extracting keywords...", 35)
    keywords     = extract_keywords(df["clean_text"].tolist())
    pos_texts    = df[df["vader_label"]=="Positive"]["clean_text"].tolist()
    neg_texts    = df[df["vader_label"]=="Negative"]["clean_text"].tolist()
    pos_keywords = extract_keywords(pos_texts, 10) if len(pos_texts)>=2 else []
    neg_keywords = extract_keywords(neg_texts, 10) if len(neg_texts)>=2 else []

    set_progress(4,"Running TextBlob sample...", 40)
    sample_size = min(total, 300)
    sample_idx  = np.random.choice(total, sample_size, replace=False)
    tb_labels   = [textblob_label_one(df["clean_text"].iloc[i])
                   for i in sample_idx]
    tc = pd.Series(tb_labels).value_counts()

    vc = df["vader_label"].value_counts()
    vader_stats = {
        "positive":     int(vc.get("Positive",0)),
        "negative":     int(vc.get("Negative",0)),
        "neutral":      int(vc.get("Neutral",0)),
        "positive_pct": round(vc.get("Positive",0)/total*100,1),
        "negative_pct": round(vc.get("Negative",0)/total*100,1),
        "neutral_pct":  round(vc.get("Neutral",0)/total*100,1),
    }
    tb_stats = {
        "positive_pct": round(tc.get("Positive",0)/sample_size*100,1),
        "negative_pct": round(tc.get("Negative",0)/sample_size*100,1),
        "neutral_pct":  round(tc.get("Neutral",0)/sample_size*100,1),
    }

    ml_stats = {"available": False}

    if total >= 20 and df["vader_label"].nunique() >= 2:
        try:
            set_progress(5,"Preparing training data...", 48)
            X = df["clean_text"]
            y = df["vader_label"]

            # Safe test size
            test_sz = 0.2 if total >= 50 else 0.25

            X_tr, X_te, y_tr, y_te = train_test_split(
                X, y, test_size=test_sz,
                random_state=42, stratify=y)

            label_order = ["Positive","Neutral","Negative"]
            n_classes   = y.nunique()
            n_folds     = safe_cv_folds(total, n_classes)

            models = get_models()

            set_progress(6,"Training models...", 55)
            raw = Parallel(n_jobs=2, backend="threading")(
                delayed(train_one)(
                    name, pipe, X_tr, X_te,
                    y_tr, y_te, label_order, X, y,
                    n_folds)
                for name, pipe in models.items()
            )
            results = {name: res for name, res in raw}

            set_progress(7,"Selecting best model...", 80)
            valid = {n: r for n,r in results.items()
                     if "f1" in r}
            if not valid:
                raise Exception("All models failed")

            best_n = max(valid, key=lambda n: valid[n]["f1"])
            best   = valid[best_n]

            set_progress(8,"Saving model...", 88)
            out_dir    = os.path.join("static","outputs")
            os.makedirs(out_dir, exist_ok=True)
            model_path = os.path.join(out_dir,"best_model.pkl")
            if "pipeline" in best:
                with open(model_path,"wb") as f:
                    pickle.dump(best["pipeline"],f)

            clean_res = {
                n: {k:v for k,v in r.items() if k!="pipeline"}
                for n,r in results.items()
            }

            set_progress(9,"Finalising...", 95)
            ml_stats = {
                "available":        True,
                "model_results":    clean_res,
                "best_model":       best_n,
                "best_f1":          best.get("f1",0),
                "best_accuracy":    best.get("accuracy",0),
                "confusion_matrix": best.get("confusion_matrix",[]),
                "cm_labels":        label_order,
                "per_class":        best.get("per_class",{}),
                "cv_each_fold":     best.get("cv_each_fold",[]),
                "cv_mean":          best.get("cv_mean",0) or 0,
                "cv_std":           best.get("cv_std",0)  or 0,
                "auc":              best.get("auc"),
                "train_size":       len(X_tr),
                "test_size":        len(X_te),
                "k_folds":          n_folds or 0,
                "total_models":     len(clean_res),
            }

        except Exception as e:
            ml_stats = {"available":False,"error":str(e)}

    set_progress(10,"Done!",100)
    return {
        "available":     True,
        "text_column":   text_col,
        "total_samples": total,
        "vader":         vader_stats,
        "textblob":      tb_stats,
        "ml":            ml_stats,
        "keywords":      keywords,
        "pos_keywords":  pos_keywords,
        "neg_keywords":  neg_keywords,
        "positive":      vader_stats["positive"],
        "negative":      vader_stats["negative"],
        "neutral":       vader_stats["neutral"],
        "positive_pct":  vader_stats["positive_pct"],
        "negative_pct":  vader_stats["negative_pct"],
        "neutral_pct":   vader_stats["neutral_pct"],
    }