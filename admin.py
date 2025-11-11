from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from functools import wraps

admin_bp = Blueprint('admin', __name__, template_folder='templates', static_folder='static')

# Default admin credential (change in production!)
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "123456"

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Bạn cần đăng nhập để truy cập trang quản trị.", "warning")
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated

@admin_bp.route("/admin/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        # Simple check against default credential
        if username == DEFAULT_ADMIN_USER and password == DEFAULT_ADMIN_PASS:
            session["admin_logged_in"] = True
            flash("Đăng nhập thành công.", "success")
            return redirect(url_for('index'))
        else:
            flash("Sai tài khoản hoặc mật khẩu.", "danger")
            return render_template("admin/login.html", username=username)
    return render_template("admin/login.html")

@admin_bp.route("/admin/logout")
def logout():
    session.pop("admin_logged_in", None)
    flash("Bạn đã đăng xuất.", "info")
    return redirect(url_for("admin.login"))

@admin_bp.route("/admin/dashboard")
@admin_required
def dashboard():
    # Simple dashboard: show some files in uploads/outputs if available
    base = current_app.root_path
    uploads = []
    outputs = []
    try:
        uploads_dir = os.path.join(base, "uploads")
        outputs_dir = os.path.join(base, "outputs")
        if os.path.isdir(uploads_dir):
            uploads = sorted(os.listdir(uploads_dir))[-20:]
        if os.path.isdir(outputs_dir):
            outputs = sorted(os.listdir(outputs_dir))[-20:]
    except Exception:
        pass
    return render_template("admin/dashboard.html", uploads=uploads, outputs=outputs)
