# -*- coding: utf-8 -*-
import io, os, time
from pathlib import Path
import pandas as pd
import joblib
from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, flash, session
)

# ---------------- CONFIG ----------------
BASE_DIR   = Path(__file__).parent
MODEL_PATH = BASE_DIR / "runs_xgb" / "xgb_tfidf_pipeline.joblib"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
MAX_MB     = 20  # giới hạn dung lượng upload

for d in (UPLOAD_DIR, OUTPUT_DIR):
    d.mkdir(exist_ok=True)

# ---------------- APP INIT ----------------
app = Flask(__name__)
app.secret_key = "change_this_to_a_random_secret_key_123456"
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

# ---------------- IMPORT ADMIN ----------------
from admin import admin_bp
app.register_blueprint(admin_bp)

# ---------------- FORCE LOGIN FIRST ----------------
EXEMPT_ENDPOINTS = {
    "admin.login",
    "static"
}
EXEMPT_PATH_PREFIXES = (
    "/admin/login",
    "/admin/logout",
    "/favicon.ico",
)

@app.before_request
def _force_login_first():
    if session.get("admin_logged_in"):
        return
    ep = request.endpoint or ""
    path = request.path or ""
    if ep in EXEMPT_ENDPOINTS or any(path.startswith(p) for p in EXEMPT_PATH_PREFIXES):
        return
    return redirect(url_for("admin.login"))

# ---------------- LOAD MODEL ----------------
try:
    bundle = joblib.load(MODEL_PATH)
    PIPELINE  = bundle["pipeline"]
    LABEL_MAP = bundle.get("label_map", {"neg": 0, "pos": 1})
except Exception as e:
    raise RuntimeError(f"Không thể load model tại {MODEL_PATH}: {e}")

# ---------------- UTILS ----------------
CANDIDATE_TEXT_COLS = ["text", "comment", "message", "content", "review", "sentence"]

def read_csv_robust(path: Path) -> pd.DataFrame:
    errors = []
    for enc in ("utf-8", "utf-8-sig", "cp1258", "cp1252", "latin-1"):
        try:
            return pd.read_csv(path, sep=None, engine="python", encoding=enc)
        except Exception as e:
            errors.append(f"{enc}: {e}")
    raise ValueError("Không đọc được CSV. Thử các encoding đều lỗi:\n" + "\n".join(errors))

def pick_text_col(df: pd.DataFrame):
    for c in df.columns:
        if c.lower() in CANDIDATE_TEXT_COLS:
            return c
    obj_cols = [c for c in df.columns if df[c].dtype == "object"]
    if obj_cols:
        lengths = {c: df[c].astype(str).str.len().mean() for c in obj_cols}
        return max(lengths, key=lengths.get)
    return None

# ---------------- ROUTES ----------------
@app.route("/", methods=["GET", "POST"])
def index():
    # Inline guard: nếu chưa đăng nhập thì chuyển sang trang login
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin.login'))

    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename.lower().endswith(".csv"):
            flash("❌ Vui lòng tải lên tệp CSV hợp lệ (.csv).", "danger")
            return redirect(url_for("index"))

        ts = int(time.time())
        save_path = UPLOAD_DIR / f"input_{ts}.csv"
        file.save(save_path)

        try:
            df = read_csv_robust(save_path)
        except Exception as e:
            flash(f"❌ Lỗi đọc file CSV: {e}", "danger")
            return redirect(url_for("index"))

        text_col = pick_text_col(df)
        if not text_col:
            flash("❌ Không tìm thấy cột văn bản hợp lệ.", "danger")
            return redirect(url_for("index"))

        df = df[[text_col]].rename(columns={text_col: "text"}).dropna()
        df["text"] = df["text"].astype(str).str.strip()
        df = df[df["text"] != ""]
        if df.empty:
            flash("❌ File không có dòng hợp lệ.", "danger")
            return redirect(url_for("index"))

        # inference
        probs = PIPELINE.predict_proba(df["text"])
        df["prob_neg"]   = probs[:, 0]
        df["prob_pos"]   = probs[:, 1]
        df["pred_label"] = df["prob_pos"].apply(lambda p: "pos" if p >= 0.5 else "neg")

        # stats
        total = len(df)
        pos_count = int((df["pred_label"] == "pos").sum())
        neg_count = int((df["pred_label"] == "neg").sum())
        pos_pct = round(pos_count / total * 100, 2)
        neg_pct = round(neg_count / total * 100, 2)

        # output file
        out_path = OUTPUT_DIR / f"result_{ts}.csv"
        df.to_csv(out_path, index=False)

        # --------- NEW: Lưu vào session cho Charts/Insights ---------
        session["last_stats"] = {
            "total": total,
            "pos": pos_count,
            "neg": neg_count,
            "pos_pct": pos_pct,
            "neg_pct": neg_pct,
        }
        # Top bình luận tích cực/tiêu cực (dựa theo xác suất)
        top_positive = df.sort_values("prob_pos", ascending=False).head(5)["text"].tolist()
        top_negative = df.sort_values("prob_neg", ascending=False).head(5)["text"].tolist()
        session["last_top_positive"] = top_positive
        session["last_top_negative"] = top_negative
        # ------------------------------------------------------------

        return render_template(
            "result.html",
            tables=df.head(10000).to_dict(orient="records"),
            total=total,
            pos=pos_count,
            neg=neg_count,
            pos_pct=pos_pct,
            neg_pct=neg_pct,
            filename=out_path.name
        )

    return render_template("index.html")

@app.route("/predict", methods=["POST"])
def predict():
    text = (request.form.get("single_text") or "").strip()
    if not text:
        flash("⚠️ Vui lòng nhập nội dung để dự đoán.", "warning")
        return redirect(url_for("index"))

    proba = PIPELINE.predict_proba([text])[0]
    prob_pos = float(proba[1])
    label = "pos" if prob_pos >= 0.5 else "neg"

    return render_template(
        "index.html",
        single_input=text,
        single_label=label,
        single_prob=round(prob_pos * 100, 2)
    )

@app.route("/download/<filename>")
def download(filename):
    path = OUTPUT_DIR / filename
    if not path.exists():
        flash("❌ File không tồn tại.", "danger")
        return redirect(url_for("index"))
    return send_file(path, as_attachment=True)

# ===== BIỂU ĐỒ PHÂN TÍCH =====
import functools

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        # Hệ thống đang dùng session 'admin_logged_in' (do blueprint admin)
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

@app.route("/charts", methods=["GET"], endpoint="chart")  # endpoint='chart' để url_for('chart') dùng được
@login_required
def charts_page():
    stats = session.get("last_stats", {})
    if not stats:
        # fallback: cho phép truyền nhanh qua query ?pos=..&neg=..
        try:
            pos = int(request.args.get("pos", 0))
            neg = int(request.args.get("neg", 0))
        except Exception:
            pos = neg = 0
        total = pos + neg
        pos_pct = round(pos/total*100, 2) if total else 0
        neg_pct = 100 - pos_pct if total else 0
        stats = {"pos": pos, "neg": neg, "total": total, "pos_pct": pos_pct, "neg_pct": neg_pct}

    return render_template("charts.html", stats=stats)

@app.route("/insights")
@login_required
def insights():
    # Lấy dữ liệu thống kê + top comments từ session
    stats = session.get("last_stats", {
        "total": 0, "pos": 0, "neg": 0, "pos_pct": 0, "neg_pct": 0
    })
    top_positive = session.get("last_top_positive", [])
    top_negative = session.get("last_top_negative", [])

    # Dữ liệu mẫu cho biểu đồ từ khóa (nếu bạn có xử lý keywords, thay thế phần này)
    keywords = {
        "thấy": 7, "như": 6, "cách": 6, "nghe": 3, "mình": 3,
        "đẹp": 2, "vui": 2, "buồn": 1, "đáng": 1
    }
    return render_template(
        "insights.html",
        stats=stats,
        keywords=keywords,
        top_positive=top_positive,
        top_negative=top_negative
    )

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)
