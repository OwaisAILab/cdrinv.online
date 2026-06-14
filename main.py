from flask import Flask, render_template, request, redirect, send_from_directory, jsonify, abort
from werkzeug.utils import secure_filename
import os
import pandas as pd
import sys
from datetime import datetime

# ── Auth imports ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth.database import engine, Base, SessionLocal
from auth.models import User, UserStatus, SubscriptionType
from auth.routes import auth_bp, init_auth_routes
from auth.utils import decode_token, _now, _send_email

# ── Core analysis modules ─────────────────────────────────────────────────
from core.normalizer import normalize_dataframe
from core.timeline import (
    most_contacted, hourly_activity, silent_periods,
    silent_period_residence_analysis, imei_switch_timeline, non_mobile_summary,
    imsi_switch_timeline
)
from core.map_utils import generate_map_data
from core.comparison import same_tower_same_time, common_contacts
from core.relationship import direct_contacts, relationship_score_engine, relationship_intelligence
from core.network_graph import build_network_data
from core.movement import (
    workplace_analysis, daily_route_analysis,
    route_frequency_analysis, movement_radius_analysis,
    unusual_travel_detection, unusual_days_only
)
from core.mhe import meeting_hotspots, hotspot_dates

# ── Create tables if not exist ────────────────────────────────────────────
Base.metadata.create_all(engine)

# ── Flask app setup ───────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-in-production")
app.config['UPLOAD_FOLDER'] = os.getenv("UPLOAD_FOLDER", "uploads")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ── Make `request` available in all templates automatically ──────────────
@app.context_processor
def inject_request():
    return dict(request=request)

# ── Global state ──────────────────────────────────────────────────────────
latest_normalized_df = None
latest_non_mobile_df = None
latest_data_sessions_df = None
latest_dashboard_data = {}
latest_map_data = []
latest_residence_data = []
latest_comparison_data = {}
latest_network_data = {}

# ── Helper: get current user as a dict ────────────────────────────────────
def get_current_user():
    token = request.cookies.get("access_token")
    if not token:
        abort(401)
    payload = decode_token(token)
    if not payload:
        abort(401)
    user_id = payload.get("sub")
    if not user_id:
        abort(401)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user or user.status != UserStatus.ACTIVE:
            abort(401)
        if user.subscription_end and user.subscription_end < _now():
            abort(401)
        user_data = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'subscription_type': user.subscription_type,
            'uploads_remaining': user.uploads_remaining,
            'status': user.status
        }
        db.close()
        return user_data
    except Exception:
        db.close()
        abort(401)

# ── Register auth blueprint ──────────────────────────────────────────────
init_auth_routes(app)

# ── Helper: read uploaded file ───────────────────────────────────────────
def read_uploaded_file(filepath, filename):
    ext = filename.split('.')[-1].lower()
    if ext == 'csv':
        return pd.read_csv(filepath, dtype=str)
    elif ext == 'xlsx':
        return pd.read_excel(filepath, dtype=str)
    elif ext == 'xls':
        return pd.read_excel(filepath, engine='xlrd', dtype=str)
    else:
        raise ValueError("Only CSV/XLS/XLSX supported")

# ─────────────────────────────────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("landing.html")

@app.route("/subscribe")
def subscribe_page():
    return render_template("subscribe.html")

@app.route("/blog")
def blog_page():
    # Create a simple blog.html or redirect
    return render_template("blog.html") if os.path.exists("templates/blog.html") else redirect("/")

@app.route("/faq")
def faq_page():
    return redirect("/#faq")

@app.route("/knowledge")
def knowledge_page():
    return redirect("/#knowledge")

@app.route("/api/rate")
def exchange_rate():
    return jsonify({"rate": 278.50, "source": "fallback"})

# ── Contact form (POST only) ─────────────────────────────────────────────
@app.route("/contact", methods=['POST'])
def contact_submit():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    contact_type = request.form.get("type", "").strip()
    message = request.form.get("message", "").strip()

    if not all([name, email, contact_type, message]):
        return render_template("landing.html", contact_error="All fields are required."), 400

    subject = f"CDR Portal Contact: {contact_type} from {name}"
    body_html = f"""
    <div style="font-family:monospace;background:#04100a;color:#e8f0eb;padding:24px;">
        <h2 style="color:#c9a84c;">New Contact Form Submission</h2>
        <p><strong>Name:</strong> {name}</p>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Type:</strong> {contact_type}</p>
        <p><strong>Message:</strong></p>
        <p style="background:#0d2218;padding:16px;border-left:3px solid #c9a84c;">{message.replace(chr(10), '<br>')}</p>
    </div>
    """
    success = _send_email("muhammadmeethani@gmail.com", subject, body_html)
    if success:
        return render_template("landing.html", contact_success="Thank you! Your message has been sent.")
    else:
        return render_template("landing.html", contact_error="Failed to send. Please try again later."), 500

@app.route("/upload")
def upload_page():
    user = get_current_user()
    return render_template("upload.html",
                           username=user['username'],
                           subscription_type=user['subscription_type'].value)

@app.route("/upload-cdr/", methods=['POST'])
def upload_cdr():
    global latest_normalized_df, latest_non_mobile_df, latest_data_sessions_df, latest_map_data, latest_network_data, latest_residence_data, latest_dashboard_data
    user = get_current_user()

    if user['subscription_type'] == SubscriptionType.ONE_MONTH:
        if user['uploads_remaining'] == 0:
            return jsonify({"status": "error", "message": "Upload limit reached (30 files). Upgrade your plan."}), 403

    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    filename = secure_filename(file.filename)
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(temp_path)

    try:
        df = read_uploaded_file(temp_path, filename)
        normalized_df, non_mobile_df, data_sessions_df = normalize_dataframe(df)
        latest_normalized_df = normalized_df
        latest_non_mobile_df = non_mobile_df
        latest_data_sessions_df = data_sessions_df

        # Run analyses (keep your existing implementation)
        latest_map_data = generate_map_data(normalized_df)
        latest_network_data = build_network_data(normalized_df)
        latest_residence_data = silent_period_residence_analysis(normalized_df)
        relationship_scores = relationship_intelligence(normalized_df)
        workplace_data = workplace_analysis(normalized_df)
        route_frequencies = route_frequency_analysis(normalized_df)
        movement_radius = movement_radius_analysis(normalized_df)

        date_range = None
        if 'call_date' in normalized_df.columns:
            dates_clean = normalized_df['call_date'].dropna()
            dates_clean = dates_clean[dates_clean.astype(str).str.strip() != '']
            if len(dates_clean) > 0:
                try:
                    date_range = {"min_date": str(dates_clean.min()), "max_date": str(dates_clean.max())}
                except Exception:
                    pass

        latest_dashboard_data = {
            "summary": {
                "records": len(normalized_df),
                "contacts": normalized_df["contact_number"].nunique(),
                "towers": normalized_df["tower_address"].nunique(),
                "non_mobile_contacts": len(non_mobile_df),
                "data_sessions": len(data_sessions_df),
                "imei_switches": int(normalized_df["imei_switch"].sum()) if "imei_switch" in normalized_df.columns else 0,
                "imsi_switches": int(normalized_df["imsi_switch"].sum()) if "imsi_switch" in normalized_df.columns else 0
            },
            "date_range": date_range,
            "top_contacts": relationship_scores,
            "hourly": hourly_activity(normalized_df),
            "residence": latest_residence_data,
            "workplace": workplace_data,
            "silent_periods": silent_periods(normalized_df),
            "route_frequency": route_frequencies,
            "movement_radius": movement_radius,
            "relationship": relationship_scores,
            "imei_timeline": imei_switch_timeline(normalized_df),
            "imsi_timeline": imsi_switch_timeline(normalized_df),
            "non_mobile_summary": non_mobile_summary(non_mobile_df)
        }

        if user['subscription_type'] == SubscriptionType.ONE_MONTH:
            db = SessionLocal()
            try:
                db_user = db.query(User).filter(User.id == user['id']).first()
                db_user.uploads_used += 1
                db.commit()
            finally:
                db.close()

        return redirect("/dashboard", code=303)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route("/compare-cdrs/", methods=['POST'])
def compare_cdrs():
    user = get_current_user()
    if user['subscription_type'] == SubscriptionType.ONE_MONTH:
        return jsonify({"status": "error", "message": "Dual analysis requires Standard or Extended plan."}), 403

    if 'file1' not in request.files or 'file2' not in request.files:
        return jsonify({"status": "error", "message": "Both files required"}), 400
    file1 = request.files['file1']
    file2 = request.files['file2']
    if file1.filename == '' or file2.filename == '':
        return jsonify({"status": "error", "message": "Missing file"}), 400

    path1 = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file1.filename))
    path2 = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file2.filename))
    file1.save(path1)
    file2.save(path2)

    try:
        df1 = read_uploaded_file(path1, file1.filename)
        df2 = read_uploaded_file(path2, file2.filename)
        norm1, non_mobile1, data_sessions1 = normalize_dataframe(df1)
        norm2, non_mobile2, data_sessions2 = normalize_dataframe(df2)

        direct = direct_contacts(norm1, norm2)
        meetings = same_tower_same_time(norm1, norm2)
        hotspots = meeting_hotspots(meetings)
        hotspot_history = hotspot_dates(meetings)
        common = common_contacts(norm1, norm2)
        relationship = relationship_score_engine(norm1, norm2, direct, common, meetings)

        global latest_comparison_data
        latest_comparison_data = {
            "status": "success",
            "cdr_1_records": int(len(norm1)),
            "cdr_2_records": int(len(norm2)),
            "cdr_1_non_mobile_contacts": int(len(non_mobile1)),
            "cdr_2_non_mobile_contacts": int(len(non_mobile2)),
            "cdr_1_data_sessions": int(len(data_sessions1)),
            "cdr_2_data_sessions": int(len(data_sessions2)),
            "possible_meetings": meetings,
            "common_contacts": common,
            "direct_relationship": direct,
            "relationship_analysis": relationship,
            "meeting_hotspots": hotspots,
            "hotspot_history": hotspot_history
        }
        return redirect("/comparison-dashboard", code=303)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        for p in (path1, path2):
            if os.path.exists(p):
                os.remove(p)

# ── JSON endpoints ────────────────────────────────────────────────────────
@app.route("/dashboard-data")
def dashboard_data():
    return jsonify(latest_dashboard_data)

@app.route("/map-data")
def map_data():
    return jsonify(latest_map_data)

@app.route("/residence-data")
def residence_data():
    return jsonify(latest_residence_data)

@app.route("/non-mobile-data")
def non_mobile_data():
    if latest_non_mobile_df is None:
        return jsonify([])
    return jsonify(latest_non_mobile_df.to_dict(orient="records"))

@app.route("/data-sessions-data")
def data_sessions_data():
    if latest_data_sessions_df is None:
        return jsonify([])
    return jsonify(latest_data_sessions_df.to_dict(orient="records"))

@app.route("/compare-dashboard-data")
def compare_dashboard_data():
    return jsonify(latest_comparison_data)

@app.route("/network-data")
def network_data():
    return jsonify(latest_network_data)

@app.route("/filter-map-data")
def filter_map_data():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if latest_normalized_df is None:
        return jsonify([])
    df = latest_normalized_df.reset_index(drop=True)
    if (start_date or end_date) and "call_date" in df.columns:
        col = df["call_date"].astype(str)
        if start_date and end_date:
            filtered = df[col.between(start_date, end_date)]
        elif start_date:
            filtered = df[col >= start_date]
        else:
            filtered = df[col <= end_date]
    else:
        filtered = df
    return jsonify(generate_map_data(filtered))

# ── Protected HTML pages ─────────────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    get_current_user()
    return render_template("dashboard.html")

@app.route("/map")
def map_page():
    get_current_user()
    return render_template("map.html")

@app.route("/residence-map")
def residence_map():
    get_current_user()
    return render_template("residence_map.html")

@app.route("/comparison-dashboard")
def comparison_dashboard():
    get_current_user()
    return render_template("comparison_dashboard.html")

@app.route("/network")
def network_page():
    get_current_user()
    return render_template("network.html")

@app.route("/filtered-map")
def filtered_map():
    get_current_user()
    return render_template("filtered_map.html")

@app.errorhandler(401)
def unauthorized(e):
    return redirect("/auth/login")

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__ == "__main__":
    app.run()