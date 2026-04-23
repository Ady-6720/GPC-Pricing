import io, requests, sqlite3, os, pytz
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Render Persistence Check
DB_FILE = "/data/rtp_data.db" if os.path.exists("/data") else "rtp_data.db"
LOCAL_TZ = pytz.timezone("America/New_York")

def init_db():
    """Initializes the database and ensures the table exists."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS prices 
            (date TEXT, time TEXT, forecast_price REAL, actual_price REAL, 
             last_finalized TEXT, PRIMARY KEY (date, time))''')
        conn.commit()

def get_security_token():
    url = "https://ws.southernco.com/securityws/nonsecure/coolsecurityns.asmx"
    payload = """<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><Login xmlns="http://ws.southernco.com/SecurityWS"><ns>COOLSECURITY:CSAPPAUTH</ns><uid>EDDC52</uid><pwd>Nd3y2G5PmAz6o8T9WkJa</pwd><authType>7</authType></Login></soap:Body></soap:Envelope>"""
    headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "http://ws.southernco.com/SecurityWS/Login"}
    try:
        r = requests.post(url, data=payload, headers=headers, timeout=10)
        return ET.fromstring(r.text).find(".//{http://ws.southernco.com/SecurityWS}LoginResult").text
    except: return None

def fetch_api(token, rtp_type, offset=0):
    zulu_now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    target_date = (datetime.now(LOCAL_TZ) + timedelta(days=offset)).strftime("%Y-%m-%d")
    url = "https://www.energydirect.com/WebServices/RTPWebService.asmx"
    payload = f"""<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Header><ScCredentials xmlns="http://ws.southernco.com/EnergyDirect"><DirectUserNameToken><BinarySecurityToken><ID>{token}</ID></BinarySecurityToken></DirectUserNameToken><Created>{zulu_now}</Created></ScCredentials></soap:Header><soap:Body><GetRTPPrices xmlns="http://ws.southernco.com/EnergyDirect"><fileFormat>CSV</fileFormat><rtpType>{rtp_type}</rtpType><startDate>{target_date}T00:00:00</startDate><endDate>{target_date}T23:59:59</endDate></GetRTPPrices></soap:Body></soap:Envelope>"""
    headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "http://ws.southernco.com/EnergyDirect/GetRTPPrices"}
    try:
        res = requests.post(url, data=payload, headers=headers, timeout=15)
        csv_text = ET.fromstring(res.text).find(".//{http://ws.southernco.com/EnergyDirect}GetRTPPricesResult").text
        return pd.read_csv(io.StringIO(csv_text), names=["Date", "Time", "Price", "Status"])
    except: return pd.DataFrame()

def refresh_task():
    token = get_security_token()
    if not token: return
    now_local = datetime.now(LOCAL_TZ)
    now_ts = now_local.strftime("%H:%M")
    
    for offset in [0, -1]:
        fct = fetch_api(token, "GPCDayAhead", offset)
        act = fetch_api(token, "GPCHourAhead", offset)
        with sqlite3.connect(DB_FILE) as conn:
            if not fct.empty:
                for _, r in fct.iterrows():
                    conn.execute("INSERT INTO prices (date, time, forecast_price) VALUES (?,?,?) ON CONFLICT(date,time) DO UPDATE SET forecast_price=excluded.forecast_price", (r['Date'], r['Time'], r['Price']))
            if not act.empty:
                for _, r in act.iterrows():
                    if r['Status'] == 'Actual':
                        conn.execute("UPDATE prices SET actual_price = ?, last_finalized = COALESCE(last_finalized, ?) WHERE date = ? AND time = ? AND actual_price IS NULL", (r['Price'], now_ts, r['Date'], r['Time']))
            conn.commit()

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        :root { --uga-gray: #333333; --uga-red: #BA0C2F; --bg: #0D1117; --card: #161B22; --border: #30363D; --text: #C9D1D9; }
        body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; font-size: 0.85rem; padding-bottom: 40px; }
        .header-bar { background: var(--uga-gray); padding: 1rem 2rem; border-bottom: 3px solid var(--uga-red); display: flex; justify-content: space-between; align-items: center; }
        .update-box { background: rgba(0,0,0,0.4); padding: 6px 14px; border-radius: 6px; border: 1px solid var(--border); font-size: 0.8rem; }
        .insight-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 1.25rem; }
        .insight-label { font-size: 0.7rem; text-transform: uppercase; color: #8B949E; margin-bottom: 5px; }
        .insight-val { font-size: 1.7rem; font-weight: 700; font-family: 'Consolas', monospace; color: #58A6FF; }
        .dashboard-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(550px, 1fr)); gap: 1.5rem; padding: 1.5rem; }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; }
        .card-header { background: #21262D; font-weight: 600; padding: 10px 20px; border-bottom: 1px solid var(--border); color: #FFF; display: flex; justify-content: space-between; }
        .table { color: var(--text); margin: 0; }
        .table thead th { background: #161B22; color: #8B949E; border-bottom: 1px solid var(--border); font-size: 0.7rem; text-transform: uppercase; text-align: center; }
        .table td { border-bottom: 1px solid #21262D; padding: 8px; text-align: center; vertical-align: middle; }
        .finalized-stamp { font-size: 0.7rem; color: #58A6FF; background: rgba(88, 166, 255, 0.1); padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(88, 166, 255, 0.2); }
        .mono { font-family: 'Consolas', monospace; }
        .diff-up { color: #F85149; font-weight: bold; }
        .diff-down { color: #3FB950; font-weight: bold; }
        .current-row { background-color: rgba(186, 12, 47, 0.1) !important; }
    </style>
</head>
<body>
    <div class="header-bar">
        <h4 class="m-0 fw-bold">UGA UEM GPC Pricing Dashboard</h4>
        <div class="d-flex gap-3">
            <div class="update-box text-center"><div class="small opacity-50">SYNCED (ATHENS)</div><div class="fw-bold">{{ ts_last }}</div></div>
            <div class="update-box text-center"><div class="small opacity-50">NEXT UPDATE</div><div class="fw-bold text-warning">{{ ts_next }}</div></div>
        </div>
    </div>
    <div class="container-fluid mt-4">
        <div class="row g-3 px-4 mb-2">
            <div class="col-md-3"><div class="insight-card"><div class="insight-label">24H High</div><div class="insight-val text-danger">{{ "%.4f"|format(stats.high) }}</div></div></div>
            <div class="col-md-3"><div class="insight-card"><div class="insight-label">24H Low</div><div class="insight-val text-success">{{ "%.4f"|format(stats.low) }}</div></div></div>
            <div class="col-md-3"><div class="insight-card"><div class="insight-label">Daily Avg</div><div class="insight-val">{{ "%.4f"|format(stats.avg) }}</div></div></div>
            <div class="col-md-3"><div class="insight-card"><div class="insight-label">Settlement Status</div><div class="insight-val" style="font-size: 1.2rem; line-height: 2.1rem;">LIVE TRACKING</div></div></div>
        </div>
        <div class="dashboard-grid">
            <div class="card">
                <div class="card-header"><span>Today Live Feed</span><span class="badge bg-dark border border-secondary">{{ date_t }}</span></div>
                <table class="table">
                    <thead><tr><th>Time</th><th>Forecast</th><th>Actual</th><th>Finalized At</th><th>Δ</th></tr></thead>
                    <tbody>
                        {% for r in today %}
                        <tr class="{{ 'current-row' if r.time[:2] == now_hour else '' }}">
                            <td class="fw-bold">{{ r.time }}</td>
                            <td class="mono opacity-75">{{ "%.4f"|format(r.forecast_price) }}</td>
                            <td class="mono fw-bold">{{ "%.4f"|format(r.actual_price) if r.actual_price else '--' }}</td>
                            <td>{% if r.last_finalized %}<span class="finalized-stamp">{{ r.last_finalized }}</span>{% else %}<span class="text-muted small">PENDING</span>{% endif %}</td>
                            <td class="mono">{% if r.actual_price %}{% set d = r.actual_price - r.forecast_price %}<span class="{{ 'diff-up' if d > 0 else 'diff-down' }}">{{ "%+.2f"|format(d) }}</span>{% endif %}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="card">
                <div class="card-header"><span>Yesterday History</span><span class="badge bg-dark border border-secondary">{{ date_y }}</span></div>
                <table class="table">
                    <thead><tr><th>Time</th><th>Actual Price</th><th>Finalized At</th><th>Accuracy</th></tr></thead>
                    <tbody>
                        {% for r in yesterday %}
                        <tr>
                            <td class="fw-bold">{{ r.time }}</td>
                            <td class="mono fw-bold">{{ "%.4f"|format(r.actual_price) if r.actual_price else '--' }}</td>
                            <td><span class="text-muted small">{{ r.last_finalized or '--' }}</span></td>
                            <td class="mono">{% if r.actual_price and r.forecast_price %}{% set d = r.actual_price - r.forecast_price %}<span class="{{ 'diff-up' if d > 0 else 'diff-down' }}">{{ "%+.2f"|format(d) }}</span>{% endif %}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    now_l = datetime.now(LOCAL_TZ)
    yest_l = now_l - timedelta(days=1)
    t_str, y_str = now_l.strftime("%m/%d/%Y"), yest_l.strftime("%m/%d/%Y")
    next_update = (now_l + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            today = conn.execute("SELECT * FROM prices WHERE date=? ORDER BY time ASC", (t_str,)).fetchall()
            yesterday = conn.execute("SELECT * FROM prices WHERE date=? ORDER BY time ASC", (y_str,)).fetchall()
            
            # Emergency refresh if no data yet
            if len(today) == 0:
                refresh_task()
                today = conn.execute("SELECT * FROM prices WHERE date=? ORDER BY time ASC", (t_str,)).fetchall()
                yesterday = conn.execute("SELECT * FROM prices WHERE date=? ORDER BY time ASC", (y_str,)).fetchall()

            all_p = [r['forecast_price'] for r in today] + [r['actual_price'] for r in today if r['actual_price']]
            stats = {"high": max(all_p) if all_p else 0, "low": min(all_p) if all_p else 0, "avg": sum(all_p)/len(all_p) if all_p else 0}
            
        return render_template_string(HTML_PAGE, today=today, yesterday=yesterday, stats=stats, 
                                      date_t=t_str, date_y=y_str, ts_last=now_l.strftime("%H:%M:%S"), 
                                      ts_next=next_update.strftime("%H:%M:%S"), now_hour=now_l.strftime("%H"))
    except sqlite3.OperationalError:
        init_db()
        return "Database initializing... please refresh in 5 seconds."

if __name__ == '__main__':
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(refresh_task, 'interval', minutes=15)
    scheduler.start()
    
    # Run once at startup
    refresh_task()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
