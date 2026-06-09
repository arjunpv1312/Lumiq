import pandas as pd
import numpy as np
import re, os, pickle, warnings, time
from pathlib import Path
warnings.filterwarnings("ignore")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT_DIR   = _PROJECT_ROOT / "static" / "outputs"

import nltk
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from textblob import TextBlob

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

CACHE_DIR = str(_OUTPUT_DIR / "cache")
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

_progress = {"step":0,"message":"Starting...","pct":0}

def set_progress(step, message, pct):
    _progress.update({"step":step,"message":message,"pct":pct})

def get_progress():
    return dict(_progress)

def clean_text_fast(text):
    text = str(text).lower()
    for k, v in CONTRACTIONS.items():
        text = text.replace(k, v)
    text = re.sub(r"http\S+|www\S+|@\w+|#\w+", " ", text)
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)
    text = re.sub(r"[^a-zA-Z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    tokens = [
        LEMMATIZER.lemmatize(w)
        for w in text.split()
        if len(w) > 1 and (w not in STOP_WORDS or w in NEGATION)
    ]
    return " ".join(tokens)

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

_saved_pipeline = None

def predict_live(text):
    global _saved_pipeline
    clean      = clean_text_fast(text)
    vader_score = VADER_INST.polarity_scores(str(text))["compound"]
    result = {
        "vader_label":   vader_label_one(text),
        "vader_score":   round(vader_score, 3),
        "ml_label":      None,
        "ml_confidence": None,
    }
    model_path = str(_OUTPUT_DIR / "best_model.pkl")

    if os.path.exists(model_path):
        try:
            if _saved_pipeline is None:
                with open(model_path,"rb") as f:
                    _saved_pipeline = pickle.load(f)
            label = _saved_pipeline.predict([clean])[0]
            conf  = None
            if hasattr(_saved_pipeline, "predict_proba"):
                proba = _saved_pipeline.predict_proba([clean])[0]
                conf  = round(float(max(proba)) * 100, 1)
            elif hasattr(_saved_pipeline, "decision_function"):
                dec = _saved_pipeline.decision_function([clean])[0]
                try:
                    if hasattr(dec, "__len__") and len(dec) > 1:
                        exp_dec = np.exp(dec - np.max(dec))
                        proba = exp_dec / np.sum(exp_dec)
                        conf = round(float(max(proba)) * 100, 1)
                    else:
                        val = float(dec)
                        prob_pos = 1 / (1 + np.exp(-val))
                        conf = round(float(max(prob_pos, 1 - prob_pos)) * 100, 1)
                except Exception:
                    conf = 95.0
            result["ml_label"]      = label
            result["ml_confidence"] = conf
        except Exception:
            pass
    return result

def detect_ground_truth(df):
    """Detect if there is a rating or sentiment column in the dataset to use as ground truth labels."""
    # List of common sentiment column names
    sent_cols = ["sentiment", "label", "sentiment_label", "target", "score_label"]
    for col in df.columns:
        if col.lower() in sent_cols:
            vals = df[col].dropna().unique()
            if len(vals) >= 2:
                return col, "sentiment"
                
    # List of common rating column names
    rating_cols = ["rating", "rating_score", "stars", "score", "user_rating"]
    for col in df.columns:
        if col.lower() in rating_cols:
            try:
                nums = pd.to_numeric(df[col], errors='coerce').dropna()
                if not nums.empty and nums.min() >= 0 and nums.max() <= 10:
                    return col, "rating"
            except Exception:
                pass
                
    return None, None

def get_models():
    cfg = dict(max_features=5000, ngram_range=(1,2),
               sublinear_tf=True, min_df=2,
               strip_accents="unicode", stop_words="english")
    return {
        "Logistic Regression": Pipeline([
            ("tfidf", TfidfVectorizer(**cfg)),
            ("clf",   LogisticRegression(
                C=2.0, max_iter=1000, solver="liblinear",
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
            ("clf",   LinearSVC(C=0.5, max_iter=1000,
                                random_state=42,
                                class_weight="balanced")),
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
            elif hasattr(pipe.named_steps["clf"],"decision_function"):
                le  = LabelEncoder()
                yte = le.fit_transform(y_te)
                dec = pipe.decision_function(X_te)
                if len(dec.shape) > 1 and dec.shape[1] > 1:
                    exp_dec = np.exp(dec - np.max(dec, axis=1, keepdims=True))
                    yp = exp_dec / np.sum(exp_dec, axis=1, keepdims=True)
                else:
                    yp = 1 / (1 + np.exp(-dec))
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

    # Detect ground truth labels (rating or sentiment columns)
    gt_col, gt_type = detect_ground_truth(df)
    if gt_col:
        if gt_type == "rating":
            def rating_to_sentiment(r):
                try:
                    val = float(r)
                    if val >= 4.0: return "Positive"
                    elif val <= 2.0: return "Negative"
                    else: return "Neutral"
                except Exception:
                    return "Neutral"
            df["gt_label"] = df[gt_col].apply(rating_to_sentiment)
        else:
            def standardize_sentiment(s):
                s_str = str(s).strip().lower()
                if s_str in ["positive", "pos", "1", "2", "4", "5", "good"]: return "Positive"
                elif s_str in ["negative", "neg", "0", "bad"]: return "Negative"
                else: return "Neutral"
            df["gt_label"] = df[gt_col].apply(standardize_sentiment)
        df["target_label"] = df["gt_label"]
    else:
        df["target_label"] = df["vader_label"]

    if total >= 20 and df["target_label"].nunique() >= 2:
        try:
            set_progress(5,"Preparing training data...", 48)
            X = df["clean_text"]
            y = df["target_label"]

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
            out_dir    = str(_OUTPUT_DIR)
            os.makedirs(out_dir, exist_ok=True)
            model_path = str(_OUTPUT_DIR / "best_model.pkl")

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