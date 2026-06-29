from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, send_from_directory, jsonify, abort
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
import os
import pandas as pd
import sys
import pickle
# ── Auth imports ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth.database import engine, Base, SessionLocal
from auth.models import User, UserStatus, SubscriptionType
from auth.routes import auth_bp, init_auth_routes
from auth.utils import decode_token, _now, _send_email

# ── Core analysis modules ─────────────────────────────────────────────────
from core.normalizer import normalize_dataframe, read_cdr_excel
from core.timeline import (
    hourly_activity, silent_periods,
    silent_period_residence_analysis, imei_switch_timeline, non_mobile_summary,
    imsi_switch_timeline
)
from core.map_utils import generate_map_data
from core.comparison import same_tower_same_time, common_contacts
from core.relationship import direct_contacts, relationship_score_engine, relationship_intelligence
from core.network_graph import build_network_data
from core.movement import (
    workplace_analysis,
    route_frequency_analysis, movement_radius_analysis
)
from core.mhe import meeting_hotspots, hotspot_dates

from core.operational_intel import (
    generate_operational_report,
    format_operational_report
)

from core.imsi_utils import load_plmn_database, get_network_info_from_imsi
from core.tac_utils import load_tac_database, get_device_info_from_imei
from core.pattern_analysis import burst_detection, first_contact_analysis, call_abandonment_analysis

# ── Create tables if not exist ────────────────────────────────────────────
Base.metadata.create_all(engine)



# ── Flask app setup ───────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.config["WTF_CSRF_TIME_LIMIT"] = None
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")
if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY environment variable not set.")
app.config['UPLOAD_FOLDER'] = os.getenv("UPLOAD_FOLDER", "uploads")
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


load_dotenv()
load_plmn_database()
load_tac_database()

# ── Make `request` available in all templates automatically ──────────────
@app.context_processor
def inject_request():
    from flask_wtf.csrf import generate_csrf
    return dict(request=request, csrf_token=generate_csrf)

# ── Global state – per‑user data (FIX: concurrency) ──────────────────────
def _user_data_path(user_id):
    return os.path.join(app.config['UPLOAD_FOLDER'], f"session_{user_id}.pkl")

def get_user_data(user_id):
    path = _user_data_path(user_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'rb') as f:
            return pickle.load(f)
    except Exception:
        return {}

def set_user_data(user_id, data):
    path = _user_data_path(user_id)
    tmp_path = path + '.tmp'
    try:
        with open(tmp_path, 'wb') as f:
            pickle.dump(data, f)
        os.chmod(tmp_path, 0o600)  # owner read/write only before rename
        os.replace(tmp_path, path)  # atomic rename — no partial reads
    except Exception:
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except OSError: pass
        raise

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
init_auth_routes(app, limiter)

# ── Helper: read uploaded file (use read_cdr_excel for Excel) ────────────
def read_uploaded_file(filepath, filename):
    ext = filename.split('.')[-1].lower()
    if ext == 'csv':
        return pd.read_csv(filepath, dtype=str)
    elif ext in ('xlsx', 'xls'):
        return read_cdr_excel(filepath)
    else:
        raise ValueError("Only CSV/XLS/XLSX supported")

# ─────────────────────────────────────────────────────────────────────────
#  ROUTES (unchanged from your version, kept for completeness)
# ─────────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("landing.html")

@app.route("/subscribe")
def subscribe_page():
    return render_template("subscribe.html")

@app.route("/blog")
def blog_page():
    try:
        return render_template("blog.html")
    except Exception:
        return redirect("/")

@app.route("/faq")
def faq_page():
    return redirect("/#faq")

@app.route("/knowledge")
def knowledge_page():
    return render_template("knowledge.html")

@app.route("/api/rate")
def exchange_rate():
    return jsonify({"rate": 278.50, "source": "fallback"})

# ── Contact form (POST only) ─────────────────────────────────────────────
@app.route("/contact", methods=['POST'])
@limiter.limit("5 per minute")
def contact_submit():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    contact_type = request.form.get("type", "").strip()
    message = request.form.get("message", "").strip()

    if not all([name, email, contact_type, message]):
        return render_template("landing.html", contact_error="All fields are required."), 400

    import html as _he
    s_name = _he.escape(name); s_email = _he.escape(email)
    s_type = _he.escape(contact_type); s_msg = _he.escape(message).replace("\n", "<br>")
    subject = f"CDR Portal Contact: {contact_type} from {name}"
    body_html = f"""
    <div style="font-family:monospace;background:#04100a;color:#e8f0eb;padding:24px;">
        <h2 style="color:#c9a84c;">New Contact Form Submission</h2>
        <p><strong>Name:</strong> {s_name}</p>
        <p><strong>Email:</strong> {s_email}</p>
        <p><strong>Type:</strong> {s_type}</p>
        <p><strong>Message:</strong></p>
        <p style="background:#0d2218;padding:16px;border-left:3px solid #c9a84c;">{s_msg}</p>
    </div>
    """
    admin_email = os.getenv("ADMIN_EMAIL") or os.getenv("SMTP_USER")
    success = _send_email(admin_email, subject, body_html)
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
@csrf.exempt
@limiter.limit("5 per minute")
def upload_cdr():
    user = get_current_user()
    uid = user['id']


    if user['subscription_type'] in (SubscriptionType.TRIAL, SubscriptionType.ONE_MONTH):
        limit = user.get('cdr_limit') or (5 if user['subscription_type'] == SubscriptionType.TRIAL else 30)
        if user.get('uploads_used', 0) >= limit:
            return jsonify({"status": "error", "message": f"Upload limit reached ({limit} files). Upgrade your plan."}), 403

    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    filename = secure_filename(file.filename)
    allowed_ext = {'csv', 'xlsx', 'xls'}
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in allowed_ext:
        return jsonify({"status": "error", "message": "Only CSV, XLSX and XLS files are accepted."}), 400
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{uid}_{filename}")
    file.save(temp_path)

    try:
        df = read_uploaded_file(temp_path, filename)
        normalized_df, non_mobile_df, data_sessions_df = normalize_dataframe(df)

        map_data = generate_map_data(normalized_df)
        network_data = build_network_data(normalized_df)
        residence_data = silent_period_residence_analysis(normalized_df)
        relationship_scores = relationship_intelligence(normalized_df)
        workplace_data = workplace_analysis(normalized_df)
        route_frequencies = route_frequency_analysis(normalized_df)
        movement_radius = movement_radius_analysis(normalized_df)

        # ── Extract all unique IMSIs ────────────────────────────────
        network_info_list = []
        if 'imsi' in normalized_df.columns and len(normalized_df) > 0:
            imsi_series = normalized_df['imsi'].dropna()
            if len(imsi_series) > 0:
                unique_imsis = imsi_series.unique()   # get all unique IMSIs
                for imsi_val in unique_imsis:
                    imsi_str = str(imsi_val).strip()
                    if imsi_str:
                        info = get_network_info_from_imsi(imsi_str)
                        if info:
                            network_info_list.append(info)
                if network_info_list:
                    print(f"✅ Found {len(network_info_list)} unique IMSI entries")
                else:
                    print("⚠️  No valid IMSI network info found")
            else:
                print("⚠️  IMSI column exists but all values are empty.")
        else:
            print("⚠️  IMSI column not found in normalized dataframe.")


        # ── Extract all unique IMEIs for device info ────────────────
        device_info_list = []
        if 'imei' in normalized_df.columns and len(normalized_df) > 0:
            imei_series = normalized_df['imei'].dropna()
            if len(imei_series) > 0:
                unique_imeis = imei_series.unique()
                for imei_val in unique_imeis:
                    imei_str = str(imei_val).strip()
                    if imei_str:
                        info = get_device_info_from_imei(imei_str)
                        if info:   # info is never None now, but keep check
                            device_info_list.append(info)
                print(f"✅ Found {len(device_info_list)} unique IMEI entries")
            else:
                print("⚠️  IMEI column exists but all values are empty.")
        else:
            print("⚠️  IMEI column not found in normalized dataframe.")
        date_range = None
        if 'call_date' in normalized_df.columns:
            dates_clean = normalized_df['call_date'].dropna()
            dates_clean = dates_clean[dates_clean.astype(str).str.strip() != '']
            if len(dates_clean) > 0:
                try:
                    date_range = {"min_date": str(dates_clean.min()), "max_date": str(dates_clean.max())}
                except Exception:
                    pass
        
        
        dashboard_data = {
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
            "residence": residence_data,
            "workplace": workplace_data,
            "silent_periods": silent_periods(normalized_df),
            "route_frequency": route_frequencies,
            "movement_radius": movement_radius,
            "relationship": relationship_scores,
            "imei_timeline": imei_switch_timeline(normalized_df),
            "imsi_timeline": imsi_switch_timeline(normalized_df),
            "non_mobile_summary": non_mobile_summary(non_mobile_df),
            "burst_detection": burst_detection(normalized_df),
            "call_abandonment": call_abandonment_analysis(normalized_df),
            "first_contact": first_contact_analysis(normalized_df),
        }

        set_user_data(uid, {
            'normalized': normalized_df,
            'non_mobile': non_mobile_df,
            'data_sessions': data_sessions_df,
            'map_data': map_data,
            'network_data': network_data,
            'residence_data': residence_data,
            'workplace_data': workplace_data,
            'dashboard_data': dashboard_data,
            'comparison_data': {},
            'device_info_list': device_info_list,
            'network_info_list': network_info_list,
            'is_trial': user['subscription_type'] == SubscriptionType.TRIAL,
            'is_extended': user['subscription_type'] == SubscriptionType.ONE_YEAR
        })

        try:
            os.remove(temp_path)
        except OSError:
            pass

        if user['subscription_type'] in (SubscriptionType.TRIAL, SubscriptionType.ONE_MONTH):
            db = SessionLocal()
            try:
                db_user = db.query(User).filter(User.id == uid).first()
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
@csrf.exempt
@limiter.limit("5 per minute")
def compare_cdrs():
    user = get_current_user()
    uid = user['id']
    if user['subscription_type'] in (SubscriptionType.ONE_MONTH, SubscriptionType.TRIAL):
        return jsonify({"status": "error", "message": "Dual analysis requires Standard or Extended plan."}), 403

    if 'file1' not in request.files or 'file2' not in request.files:
        return jsonify({"status": "error", "message": "Both files required"}), 400
    file1 = request.files['file1']
    file2 = request.files['file2']
    if file1.filename == '' or file2.filename == '':
        return jsonify({"status": "error", "message": "Missing file"}), 400

    allowed_ext = {'csv', 'xlsx', 'xls'}
    for f_obj, label in ((file1, 'File 1'), (file2, 'File 2')):
        fname = secure_filename(f_obj.filename)
        ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
        if ext not in allowed_ext:
            return jsonify({"status": "error", "message": f"{label}: only CSV, XLSX and XLS files are accepted."}), 400

    path1 = os.path.join(app.config['UPLOAD_FOLDER'], f"{uid}_{secure_filename(file1.filename)}")
    path2 = os.path.join(app.config['UPLOAD_FOLDER'], f"{uid}_{secure_filename(file2.filename)}")
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

        comparison_data = {
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
        user_data = get_user_data(uid)
        user_data['comparison_data'] = comparison_data
        set_user_data(uid, user_data)

        return redirect("/comparison-dashboard", code=303)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        for p in (path1, path2):
            if os.path.exists(p):
                os.remove(p)

# ── Date records endpoint ────────────────────────────────────────────────
@app.route("/date-records")
@limiter.limit("30 per minute")
def date_records():
    """
    Return every CDR record for a specific date.
    ?date=YYYY-MM-DD
    """
    user = get_current_user()
    query_date = request.args.get("date", "").strip()
    if not query_date:
        return jsonify({"error": "No date provided"}), 400

    # Basic format validation
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", query_date):
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    user_data = get_user_data(user['id'])
    df = user_data.get('normalized')
    if df is None or df.empty:
        return jsonify({"error": "No CDR data loaded"}), 404

    if "call_date" not in df.columns:
        return jsonify({"error": "CDR has no date column after normalisation"}), 500

    matched = df[df["call_date"].astype(str) == query_date].copy()
    if matched.empty:
        return jsonify({"found": False, "date": query_date, "records": [], "summary": {}})

    # Sort by time
    if "call_time" in matched.columns:
        matched = matched.sort_values("call_time")

    records = []
    for _, row in matched.iterrows():
        records.append({
            "time":         str(row.get("call_time", "")).split(".")[0],  # strip microseconds
            "contact":      str(row.get("contact_number", row.get("contact", "—"))),
            "direction":    str(row.get("direction", "")).upper(),
            "call_type":    str(row.get("call_type", "VOICE")).upper(),
            "duration":     int(row["duration"]) if pd.notna(row.get("duration")) else 0,
            "tower":        str(row.get("tower_address", "—")),
            "cell_id":      str(row.get("cell_id", "—")),
            "imei":         str(row.get("imei", "—")),
            "imsi":         str(row.get("imsi", "—")),
            "latitude":     str(row.get("latitude", "")),
            "longitude":    str(row.get("longitude", "")),
        })

    # Summary stats for the day
    total       = len(matched)
    incoming    = int((matched.get("direction", pd.Series()) == "Incoming").sum()) if "direction" in matched else 0
    outgoing    = int((matched.get("direction", pd.Series()) == "Outgoing").sum()) if "direction" in matched else 0
    calls       = int(matched[matched["call_type"].str.upper().str.contains("CALL|VOICE", na=False)].shape[0]) if "call_type" in matched else total
    sms         = int(matched[matched["call_type"].str.upper().str.contains("SMS|TEXT", na=False)].shape[0]) if "call_type" in matched else 0
    unique_cont = int(matched["contact_number"].nunique()) if "contact_number" in matched else 0
    dur_series  = matched["duration"].dropna().astype(float) if "duration" in matched else pd.Series(dtype=float)
    total_dur   = int(dur_series.sum()) if not dur_series.empty else 0

    towers_used = []
    if "tower_address" in matched.columns:
        towers_used = matched["tower_address"].dropna().unique().tolist()[:10]

    return jsonify({
        "found":   True,
        "date":    query_date,
        "records": records,
        "summary": {
            "total_records":   total,
            "incoming":        incoming,
            "outgoing":        outgoing,
            "calls":           calls,
            "sms":             sms,
            "unique_contacts": unique_cont,
            "total_duration":  total_dur,
            "towers_used":     towers_used,
        }
    })

# ── JSON endpoints ──────────────────────────────────────────────────────
@app.route("/dashboard-data")
def dashboard_data():
    user = get_current_user()
    data = get_user_data(user['id']).get('dashboard_data', {})
    return jsonify(data)

@app.route("/contact-search")
def contact_search():
    """
    Search all CDR records for a specific contact number.
    Returns JSON with every call record involving that contact,
    plus summary stats (total calls, total duration, first/last seen,
    towers used, direction breakdown).
    """
    user  = get_current_user()
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "No contact number provided"}), 400

    user_data = get_user_data(user['id'])
    df = user_data.get('normalized')
    if df is None or df.empty:
        return jsonify({"error": "No CDR data loaded"}), 404

    # Normalize query the same way comparison.py does
    def _norm(val):
        val = str(val).strip().replace(" ", "").replace("-", "")
        if val.startswith("+"):   val = val[1:]
        if val.startswith("0092"): val = val[4:]
        if val.startswith("92") and len(val) == 12:   return val
        if val.startswith("03") and len(val) == 11:   return "92" + val[1:]
        if val.startswith("3")  and len(val) == 10:   return "92" + val
        if val.startswith("0"):
            s = val.lstrip("0")
            if s.startswith("3") and len(s) == 10:    return "92" + s
        return val

    norm_query = _norm(query)

    # Match against normalized contact numbers
    mask = df["contact_number"].astype(str).apply(_norm) == norm_query
    matched = df[mask].copy()

    if matched.empty:
        return jsonify({"found": False, "contact": query, "records": [], "summary": {}})

    # Build datetime for sorting
    matched["_dt"] = pd.to_datetime(
        matched["call_date"].astype(str) + " " + matched["call_time"].astype(str),
        errors="coerce"
    )
    matched = matched.sort_values("_dt")

    records = []
    for _, row in matched.iterrows():
        records.append({
            "date":      str(row.get("call_date", "")),
            "time":      str(row.get("call_time", "")),
            "direction": str(row.get("direction", "")).upper(),
            "call_type": str(row.get("call_type", "VOICE")).upper(),
            "duration":  int(row["duration"]) if pd.notna(row.get("duration")) else 0,
            "tower":     str(row.get("tower_address", "")),
            "latitude":  str(row.get("latitude", "")),
            "longitude": str(row.get("longitude", "")),
            "imei":      str(row.get("imei", "")),
            "cell_id":   str(row.get("cell_id", "")),
        })

    dur_series = matched["duration"].dropna().astype(float)
    dir_counts = matched["direction"].astype(str).str.upper().value_counts().to_dict()

    summary = {
        "total_calls":       len(records),
        "total_duration_sec": int(dur_series.sum()) if len(dur_series) > 0 else 0,
        "avg_duration_sec":  round(float(dur_series.mean()), 1) if len(dur_series) > 0 else 0,
        "first_seen":        records[0]["date"] + " " + records[0]["time"] if records else "",
        "last_seen":         records[-1]["date"] + " " + records[-1]["time"] if records else "",
        "unique_towers":     int(matched["tower_address"].nunique()),
        "direction_breakdown": dir_counts,
        "towers":            matched["tower_address"].dropna().unique().tolist(),
    }

    return jsonify({
        "found":   True,
        "contact": query,
        "summary": summary,
        "records": records,
    })

@app.route("/contact-detail")
def contact_detail():
    user = get_current_user()
    return render_template("contact_detail.html")

@app.route("/map-data")
def map_data():
    user = get_current_user()
    data = get_user_data(user['id']).get('map_data', [])
    return jsonify(data)

@app.route("/residence-data")
def residence_data():
    user = get_current_user()
    data = get_user_data(user['id']).get('residence_data', [])
    return jsonify(data)

@app.route("/non-mobile-data")
def non_mobile_data():
    user = get_current_user()
    df = get_user_data(user['id']).get('non_mobile', pd.DataFrame())
    if df is None or len(df) == 0:
        return jsonify([])
    return jsonify(df.to_dict(orient="records"))

@app.route("/data-sessions-data")
def data_sessions_data():
    user = get_current_user()
    df = get_user_data(user['id']).get('data_sessions', pd.DataFrame())
    if df is None or len(df) == 0:
        return jsonify([])
    return jsonify(df.to_dict(orient="records"))

@app.route("/compare-dashboard-data")
def compare_dashboard_data():
    user = get_current_user()
    data = get_user_data(user['id']).get('comparison_data', {})
    return jsonify(data)

@app.route("/network-data")
def network_data():
    user = get_current_user()
    data = get_user_data(user['id']).get('network_data', {})
    return jsonify(data)

@app.route("/filter-map-data")
def filter_map_data():
    user = get_current_user()
    df = get_user_data(user['id']).get('normalized', None)
    if df is None:
        return jsonify([])
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    df = df.reset_index(drop=True)
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
    user = get_current_user()
    uid = user['id']
    user_data = get_user_data(uid)
    is_trial = user_data.get('is_trial', False) or (user['subscription_type'] == SubscriptionType.TRIAL)
    trial_end = None
    if is_trial:
        db = SessionLocal()
        try:
            db_user = db.query(User).filter(User.id == uid).first()
            trial_end = db_user.subscription_end
        finally:
            db.close()
    
    device_info_list = user_data.get('device_info_list', [])
    network_info_list = user_data.get("network_info_list",[])
    has_cdr = bool(user_data.get('dashboard_data'))
    is_extended = user_data.get('is_extended', False) or (user['subscription_type'] == SubscriptionType.ONE_YEAR)
    return render_template("dashboard.html",
                           username=user['username'],
                           is_trial=is_trial,
                           trial_end=trial_end,
                           device_info_list=device_info_list,
                           network_info_list=network_info_list,
                           has_cdr=has_cdr,
                           is_extended=is_extended)

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


@app.route("/operational-intel")
def operational_intel():
    """Tactical intelligence report for field teams"""
    user = get_current_user()
    uid = user['id']
    df = get_user_data(uid).get('normalized', None)
    non_mobile = get_user_data(uid).get('non_mobile', None)
    data_sessions = get_user_data(uid).get('data_sessions', None)

    if df is None:
        return jsonify({
            'status': 'no_data',
            'message': 'Upload a CDR first to enable operational tracking.'
        })

    report = generate_operational_report(df, non_mobile, data_sessions)
    formatted = format_operational_report(report)

    if request.headers.get('Accept', '').find('text/html') != -1:
        return render_template('operational_dashboard.html',
                               intel=formatted,
                               username=user['username'])

    return jsonify(formatted)


@app.route("/workplace-data")
def workplace_data():
    user = get_current_user()
    data = get_user_data(user['id']).get('workplace_data', [])
    return jsonify(data)

@app.route("/delete-record", methods=["POST"])
@csrf.exempt
def delete_record():
    user = get_current_user()
    uid = user['id']
    path = _user_data_path(uid)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    return jsonify({"status": "ok"})

@app.route("/workplace-map")
def workplace_map():
    get_current_user()
    return render_template("workplace_map.html")

@app.route("/routes-data")
def routes_data():
    user = get_current_user()
    uid = user['id']
    user_data = get_user_data(uid)
    normalized_df = user_data.get('normalized')
    if normalized_df is None or len(normalized_df) == 0:
        return jsonify([])

    # Build tower coordinates dictionary
    tower_coords = {}
    for _, row in normalized_df.iterrows():
        addr = row.get('tower_address')
        lat = row.get('latitude')
        lon = row.get('longitude')
        if addr and lat and lon:
            try:
                lat = float(lat)
                lon = float(lon)
                if addr not in tower_coords:
                    tower_coords[addr] = (lat, lon)
            except:
                pass

    # Get route frequencies
    from core.movement import route_frequency_analysis
    routes = route_frequency_analysis(normalized_df)

    # Enrich with coordinates
    enriched_routes = []
    for route in routes:
        from_addr = route.get('from')
        to_addr = route.get('to')
        if from_addr in tower_coords and to_addr in tower_coords:
            from_lat, from_lon = tower_coords[from_addr]
            to_lat, to_lon = tower_coords[to_addr]
            enriched_routes.append({
                'from': from_addr,
                'to': to_addr,
                'frequency': route.get('frequency', 0),
                'from_lat': from_lat,
                'from_lon': from_lon,
                'to_lat': to_lat,
                'to_lon': to_lon,
            })

    # Sort by frequency descending and return ONLY the top route
    enriched_routes.sort(key=lambda x: x['frequency'], reverse=True)
    return jsonify(enriched_routes[:3])  # top 3 most frequent routes

@app.route("/routes-map")
def routes_map():
    get_current_user()
    return render_template("routes_map.html")



if __name__ == "__main__":
    app.run()