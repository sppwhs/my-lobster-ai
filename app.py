"""
台指選擇權即時看盤 — 雲端版 (Render.com)
直接部署到 Render，手機瀏覽器即可使用
"""

import os, math, time, threading, json
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import requests
import urllib3
from flask import Flask, jsonify, render_template_string

urllib3.disable_warnings()

# ─────────────────────────────────────────────
# Black-Scholes 核心計算
# ─────────────────────────────────────────────
RISK_FREE_RATE = 0.015

CALL_MONTH_CODES = {1:'A',2:'B',3:'C',4:'D',5:'E',6:'F',
                    7:'G',8:'H',9:'I',10:'J',11:'K',12:'L'}
PUT_MONTH_CODES  = {1:'M',2:'N',3:'O',4:'P',5:'Q',6:'R',
                    7:'S',8:'T',9:'U',10:'V',11:'W',12:'X'}

def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def _norm_pdf(x):
    return math.exp(-0.5 * x**2) / math.sqrt(2 * math.pi)

def _d1d2(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None, None
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    return d1, d1 - sigma*math.sqrt(T)

def bs_price(S, K, T, r, sigma, is_call):
    d1, d2 = _d1d2(S, K, T, r, sigma)
    if d1 is None:
        return max(0, (S-K) if is_call else (K-S))
    if is_call:
        return S*_norm_cdf(d1) - K*math.exp(-r*T)*_norm_cdf(d2)
    return K*math.exp(-r*T)*_norm_cdf(-d2) - S*_norm_cdf(-d1)

def bs_greeks(S, K, T, r, sigma, is_call):
    d1, d2 = _d1d2(S, K, T, r, sigma)
    if d1 is None:
        return {"delta":1.0 if is_call else -1.0,"gamma":0,"theta":0,"vega":0,"rho":0}
    pdf1 = _norm_pdf(d1)
    gamma = pdf1 / (S * sigma * math.sqrt(T))
    vega  = S * pdf1 * math.sqrt(T) * 0.01
    if is_call:
        delta = _norm_cdf(d1)
        theta = (-S*pdf1*sigma/(2*math.sqrt(T)) - r*K*math.exp(-r*T)*_norm_cdf(d2)) / 365
        rho   = K*T*math.exp(-r*T)*_norm_cdf(d2)*0.01
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-S*pdf1*sigma/(2*math.sqrt(T)) + r*K*math.exp(-r*T)*_norm_cdf(-d2)) / 365
        rho   = -K*T*math.exp(-r*T)*_norm_cdf(-d2)*0.01
    return {"delta":round(delta,4),"gamma":round(gamma,6),
            "theta":round(theta,2),"vega":round(vega,2),"rho":round(rho,4)}

def implied_volatility(S, K, T, r, price, is_call):
    if T < 0.0003 or price <= 0 or S <= 0 or K <= 0:
        return None
    intrinsic = max(0.0, (S-K) if is_call else (K-S))
    if price < intrinsic * 0.98 or (price - intrinsic) < 0.1:
        return None
    sigma = 0.25
    for _ in range(100):
        d1, d2 = _d1d2(S, K, T, r, sigma)
        if d1 is None: break
        diff = bs_price(S, K, T, r, sigma, is_call) - price
        vega = S * _norm_pdf(d1) * math.sqrt(T)
        if abs(diff) < 0.05: break
        if vega < 1e-8: break
        sigma -= diff / vega
        if sigma <= 0.001: sigma = 0.001
        if sigma > 5: break
    iv = sigma * 100
    return round(iv, 2) if 1 <= iv <= 300 else None

def time_to_expiry_years(expiry: date) -> float:
    now = datetime.now()
    exp_dt = datetime.combine(expiry, datetime.strptime("13:30","%H:%M").time())
    T = (exp_dt - now).total_seconds() / (365 * 24 * 3600)
    return max(T, 1/(365*24*12))

# ─────────────────────────────────────────────
# 到期日計算
# ─────────────────────────────────────────────
def nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n-1)

def monthly_expiry(year, month):
    return nth_weekday(year, month, 2, 3)

def get_active_contracts():
    today = date.today()
    contracts = []

    # 月選近月/次月
    found = 0
    for offset in range(3):
        yr, mo = today.year, today.month + offset
        if mo > 12: yr += 1; mo -= 12
        exp = monthly_expiry(yr, mo)
        if exp < today: continue
        label = "月選近月" if found == 0 else "月選次月"
        contracts.append({
            "label": f"{label} {yr}/{mo:02d}",
            "expiry": exp,
            "prefix": "TXO",
            "call_suffix": f"{CALL_MONTH_CODES[mo]}{yr%10}-O",
            "put_suffix":  f"{PUT_MONTH_CODES[mo]}{yr%10}-O",
            "strike_step": 100,
        })
        found += 1
        if found >= 2: break

    # 週選 TXV（最近週五）
    d = date(today.year, today.month, 1)
    fridays = []
    while d.month == today.month:
        if d.weekday() == 4: fridays.append(d)
        d += timedelta(days=1)
    for i, fr in enumerate(fridays, 1):
        if fr >= today:
            mo, yr = fr.month, fr.year
            contracts.append({
                "label": f"週選F{i} {fr.strftime('%m/%d')}",
                "expiry": fr,
                "prefix": "TXV",
                "call_suffix": f"{CALL_MONTH_CODES[mo]}{yr%10}-O",
                "put_suffix":  f"{PUT_MONTH_CODES[mo]}{yr%10}-O",
                "strike_step": 100,
            })
            break

    # 週選 TX4（第四週三）
    d = date(today.year, today.month, 1)
    weds = []
    while d.month == today.month:
        if d.weekday() == 2: weds.append(d)
        d += timedelta(days=1)
    if len(weds) >= 4:
        w4 = weds[3]
        if w4 >= today:
            mo, yr = w4.month, w4.year
            contracts.append({
                "label": f"週選W4 {w4.strftime('%m/%d')}",
                "expiry": w4,
                "prefix": "TX4",
                "call_suffix": f"{CALL_MONTH_CODES[mo]}{yr%10}-O",
                "put_suffix":  f"{PUT_MONTH_CODES[mo]}{yr%10}-O",
                "strike_step": 100,
            })
    return contracts

# ─────────────────────────────────────────────
# TAIFEX API
# ─────────────────────────────────────────────
BASE = "https://mis.bq888.taifex.com.tw/futures/api/"
HDRS = {"User-Agent": "Mozilla/5.0"}

def fetch_underlying():
    try:
        r = requests.post(BASE+"getQuoteDetail",
            json={"SymbolID":["TXO-Q","TXFD6-F"]},
            headers=HDRS, timeout=8, verify=False)
        ql = r.json().get("RtData",{}).get("QuoteList",[])
        spot = fut = 0.0
        for q in ql:
            try: val = float(q.get("CLastPrice") or q.get("CRefPrice") or 0)
            except: val = 0.0
            if q.get("SymbolID") == "TXO-Q": spot = val
            elif "TXF" in q.get("SymbolID",""): fut = val
        return spot, fut
    except: return 0.0, 0.0

def fetch_option_chain(contract, atm, wings=18):
    step = contract["strike_step"]
    atm_r = round(atm / step) * step
    strikes = [atm_r + i*step for i in range(-wings, wings+1)]
    call_syms = [f'{contract["prefix"]}{s}{contract["call_suffix"]}' for s in strikes]
    put_syms  = [f'{contract["prefix"]}{s}{contract["put_suffix"]}'  for s in strikes]
    chain_data = {}
    for batch in [call_syms[:40]+put_syms[:40], call_syms[40:]+put_syms[40:]]:
        if not batch: continue
        try:
            r = requests.post(BASE+"getQuoteDetail",
                json={"SymbolID": batch},
                headers=HDRS, timeout=10, verify=False)
            for q in r.json().get("RtData",{}).get("QuoteList",[]):
                if q.get("SymbolID"): chain_data[q["SymbolID"]] = q
        except: pass
    rows = []
    for k, cs, ps in zip(strikes, call_syms, put_syms):
        rows.append({"strike":k, "call":chain_data.get(cs,{}), "put":chain_data.get(ps,{})})
    return rows

def fetch_hv_local() -> Optional[float]:
    """優先用本機 CSV（在家用時有效）"""
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "大盤現貨.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        import pandas as pd
        df = pd.read_csv(csv_path, encoding="utf-8-sig", header=0)
        col = df.columns[4]
        closes = pd.to_numeric(df[col], errors="coerce").dropna().values
        if len(closes) < 21:
            return None
        rets = np.log(closes[-20:] / closes[-21:-1])
        return round(float(rets.std() * math.sqrt(252) * 100), 2)
    except:
        return None

def compute_atm_iv(spot: float, contract: dict, rows: list) -> Optional[float]:
    """用 ATM 選擇權 IV 的平均值估算整體波動率水準（雲端版 HV 替代）"""
    if not rows or spot <= 0:
        return None
    T = time_to_expiry_years(contract["expiry"])
    ivs = []
    for row in rows:
        k = row["strike"]
        if abs(k - spot) > contract["strike_step"] * 3:
            continue
        for q, is_call in [(row["call"], True), (row["put"], False)]:
            try:
                bid = float(q.get("CBidPrice1") or 0)
                ask = float(q.get("CAskPrice1") or 0)
                mid = (bid + ask) / 2 if bid and ask else float(q.get("CLastPrice") or 0)
                if mid <= 0:
                    continue
                iv = implied_volatility(spot, k, T, RISK_FREE_RATE, mid, is_call)
                if iv and 5 < iv < 200:
                    ivs.append(iv)
            except:
                pass
    if not ivs:
        return None
    return round(float(np.median(ivs)), 2)

# ─────────────────────────────────────────────
# 資料快取與背景刷新
# ─────────────────────────────────────────────
_cache = {"spot":0.0,"fut":0.0,"hv":25.0,"update_time":"--","contracts":[], "ready":False}
_lock  = threading.Lock()
_hv_last_fetch = 0.0
_hv_value = 25.0

def build_chain_data(contract, spot, hv, compute_atm=False):
    T = time_to_expiry_years(contract["expiry"])
    rows = fetch_option_chain(contract, spot)
    if compute_atm and hv <= 0:
        hv = compute_atm_iv(spot, contract, rows) or 25.0
    result = []
    for row in rows:
        k = row["strike"]
        cq, pq = row["call"], row["put"]
        def gf(q, key):
            try: return float(q.get(key) or 0)
            except: return 0.0
        c_bid=gf(cq,"CBidPrice1"); c_ask=gf(cq,"CAskPrice1")
        c_last=gf(cq,"CLastPrice"); c_ref=gf(cq,"CRefPrice")
        p_bid=gf(pq,"CBidPrice1"); p_ask=gf(pq,"CAskPrice1")
        p_last=gf(pq,"CLastPrice"); p_ref=gf(pq,"CRefPrice")
        mid_c = (c_bid+c_ask)/2 if c_bid and c_ask else c_last
        mid_p = (p_bid+p_ask)/2 if p_bid and p_ask else p_last
        c_iv = implied_volatility(spot, k, T, RISK_FREE_RATE, mid_c, True) if mid_c>0 and spot>0 else None
        p_iv = implied_volatility(spot, k, T, RISK_FREE_RATE, mid_p, False) if mid_p>0 and spot>0 else None
        c_sigma = (c_iv or hv)/100
        p_sigma = (p_iv or hv)/100
        cg = bs_greeks(spot, k, T, RISK_FREE_RATE, c_sigma, True)  if spot>0 else {}
        pg = bs_greeks(spot, k, T, RISK_FREE_RATE, p_sigma, False) if spot>0 else {}
        result.append({
            "strike":k,
            "c_bid":int(c_bid),"c_ask":int(c_ask),"c_last":int(c_last),"c_ref":int(c_ref),
            "c_diff":int(c_last-c_ref) if c_last else 0,"c_iv":c_iv,
            "c_delta":round(cg.get("delta",0),4),"c_gamma":round(cg.get("gamma",0),6),
            "c_theta":round(cg.get("theta",0),2),"c_vega":round(cg.get("vega",0),2),
            "c_rho":round(cg.get("rho",0),4),
            "p_bid":int(p_bid),"p_ask":int(p_ask),"p_last":int(p_last),"p_ref":int(p_ref),
            "p_diff":int(p_last-p_ref) if p_last else 0,"p_iv":p_iv,
            "p_delta":round(pg.get("delta",0),4),"p_gamma":round(pg.get("gamma",0),6),
            "p_theta":round(pg.get("theta",0),2),"p_vega":round(pg.get("vega",0),2),
            "p_rho":round(pg.get("rho",0),4),
        })
    return result

def refresh_loop():
    global _hv_last_fetch, _hv_value
    while True:
        try:
            spot, fut = fetch_underlying()
            if spot <= 0:
                time.sleep(3); continue
            # HV: 優先本機 CSV，否則用 ATM IV 估算，每小時更新一次
            if time.time() - _hv_last_fetch > 3600:
                _hv_value = fetch_hv_local() or 0.0   # 0 = 待 ATM 計算
                _hv_last_fetch = time.time()
            hv = _hv_value
            contracts_meta = get_active_contracts()
            results = []
            for ci, c in enumerate(contracts_meta):
                chain = build_chain_data(c, spot, hv, compute_atm=(ci==0 and hv<=0))
                # 若第一個合約算出 ATM IV，用作全局 HV 估算
                if ci == 0 and hv <= 0:
                    atm_iv = compute_atm_iv(spot, c, fetch_option_chain(c, spot, wings=3))
                    if atm_iv:
                        hv = atm_iv
                results.append({
                    "label": c["label"],
                    "expiry_str": c["expiry"].strftime("%Y/%m/%d"),
                    "days_left": (c["expiry"] - date.today()).days,
                    "chain": chain,
                })
            hv_source = "HV" if fetch_hv_local() else "ATM-IV"
            with _lock:
                _cache.update({
                    "spot":spot,"fut":fut,"hv":hv,"hv_source":hv_source,
                    "update_time":datetime.now().strftime("%H:%M:%S"),
                    "contracts":results,"ready":True,
                })
        except Exception as e:
            print(f"[refresh error] {e}")
        time.sleep(6)

# ─────────────────────────────────────────────
# Flask App
# ─────────────────────────────────────────────
app = Flask(__name__)

# 啟動背景刷新（gunicorn 也會執行這行）
_refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
_refresh_thread.start()

@app.route("/api/chain")
def api_chain():
    with _lock:
        if not _cache["ready"]:
            return jsonify({"ready": False})
        return jsonify({
            "ready":True,
            "spot":_cache["spot"], "fut":_cache["fut"],
            "hv":_cache["hv"], "update_time":_cache["update_time"],
            "contracts":_cache["contracts"],
        })

@app.route("/health")
def health():
    return "ok", 200

HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<title>台指選擇權</title>
<style>
:root{--bg:#0d1117;--bg2:#161b22;--bd:#30363d;--tx:#e6edf3;--dim:#8b949e;
      --red:#ff6b6b;--green:#58d68d;--yel:#f0e68c;--cy:#4dd0e1;--bl:#79b8ff;--or:#ffa07a;--atm:#1a2744}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--tx);font-family:'Courier New',monospace;font-size:13px;overflow-x:hidden}

/* Header */
#hdr{background:var(--bg2);border-bottom:1px solid var(--bd);padding:10px 12px;
     position:sticky;top:0;z-index:100}
.prow{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.pv{font-size:17px;font-weight:bold}.pl{font-size:11px;color:var(--dim)}
.sv{color:var(--red)}.fv{color:var(--yel)}.hv{color:var(--cy)}
.tv{color:var(--dim);font-size:11px;margin-left:auto}
.dot-live{display:inline-block;width:7px;height:7px;border-radius:50%;
          background:var(--green);animation:pulse 2s infinite;margin-right:4px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

/* Tabs */
#tabs{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.tb{padding:4px 10px;border-radius:4px;border:1px solid var(--bd);
    background:var(--bg);color:var(--dim);cursor:pointer;font-size:11px;
    white-space:nowrap;transition:all .2s}
.tb.active{background:#1f4068;color:var(--bl);border-color:var(--bl)}

/* View toggle */
#vtog{display:flex;margin-top:8px;gap:0}
.vb{padding:5px 14px;border:1px solid var(--bd);background:var(--bg);
    color:var(--dim);cursor:pointer;font-size:12px;transition:all .2s}
.vb:first-child{border-radius:4px 0 0 4px}
.vb:last-child{border-radius:0 4px 4px 0}
.vb.active{background:#1a3a2a;color:var(--green);border-color:var(--green)}
.dbadge{font-size:11px;padding:2px 8px;border-radius:10px;
        background:#1a2744;color:var(--bl);margin-left:6px}

/* Table */
#tw{overflow-x:auto;-webkit-overflow-scrolling:touch;padding:4px}
table{border-collapse:collapse;width:100%;min-width:720px}
th{background:#1c2030;color:var(--dim);text-align:right;padding:5px 7px;
   font-size:11px;border-bottom:1px solid var(--bd);white-space:nowrap;
   position:sticky;top:0;z-index:10}
th.ch{color:#ff9999}
th.ph{color:#88ccff}
th.sh{color:var(--yel);background:#1a1a10}
td{padding:4px 7px;text-align:right;border-bottom:1px solid #1d2433;white-space:nowrap}
tr.atm td{background:var(--atm)}
tr.ic td.cs{background:#1a1008}
tr.ip td.ps{background:#0d1a14}
td.sk{text-align:center;font-weight:bold;color:var(--yel);background:#11130d}
tr.atm td.sk{color:#fff176;background:#252510}
.cl{color:var(--red);font-weight:bold}.pl{color:var(--cy);font-weight:bold}
.cb{color:#ffaaaa}.ca{color:#ffaaaa}.pb{color:#aaddff}.pa{color:#aaddff}
.du{color:var(--red)}.dd{color:var(--cy)}
.iv{color:var(--yel)}.hvc{color:var(--dim)}
.dhi{color:var(--red);font-weight:bold}.dmd{color:var(--or)}.dlo{color:var(--tx)}
.phi{color:#58d68d;font-weight:bold}.pmd{color:#66bb6a}.plo{color:var(--tx)}
.gv{color:#b39ddb}.tv2{color:#ef9a9a}.vv{color:#80cbc4}.rv{color:var(--dim)}
.nd{color:var(--bd)}

/* Loading */
#ld{text-align:center;padding:60px 20px;color:var(--dim)}
#ldbar-w{width:200px;height:4px;background:var(--bd);border-radius:2px;margin:20px auto 0}
#ldbar{height:4px;background:var(--cy);border-radius:2px;width:0;transition:width .5s}

/* Legend */
#leg{display:flex;gap:12px;padding:6px 12px;flex-wrap:wrap;font-size:10px;
     color:var(--dim);border-top:1px solid var(--bd)}
.ld{width:8px;height:8px;border-radius:2px;display:inline-block}

@media(max-width:480px){
  body{font-size:11px}
  td,th{padding:3px 4px;font-size:10px}
  .pv{font-size:15px}
}
</style>
</head>
<body>
<div id="hdr">
  <div class="prow">
    <div><span class="pl">現貨 </span><span class="pv sv" id="sv">--</span></div>
    <div><span class="pl">期貨 </span><span class="pv fv" id="fv">--</span></div>
    <div><span class="pl" id="hv-label">HV </span><span class="pv hv" id="hv">--%</span></div>
    <div class="tv"><span class="dot-live"></span><span id="tv">--:--:--</span></div>
  </div>
  <div id="tabs"></div>
  <div style="display:flex;align-items:center;gap:10px;margin-top:8px;flex-wrap:wrap">
    <div id="vtog">
      <button class="vb active" onclick="setView('g')">Greeks</button>
      <button class="vb" onclick="setView('m')">市場報價</button>
    </div>
    <span id="db" class="dbadge"></span>
  </div>
</div>

<div id="tw">
  <div id="ld">
    <div style="font-size:36px;margin-bottom:12px">📊</div>
    <div style="font-size:16px;color:var(--tx);margin-bottom:6px">資料載入中...</div>
    <div style="font-size:12px" id="ldtxt">正在連接台灣期貨交易所</div>
    <div id="ldbar-w"><div id="ldbar"></div></div>
  </div>
  <table id="ct" style="display:none">
    <thead id="ch"></thead>
    <tbody id="cb"></tbody>
  </table>
</div>

<div id="leg">
  <span><span class="ld" style="background:#1a1008"></span> Call ITM</span>
  <span><span class="ld" style="background:#0d1a14"></span> Put ITM</span>
  <span><span class="ld" style="background:var(--atm)"></span> ATM</span>
  <span style="color:var(--yel)">IV%</span>=隱含波動率
  <span style="color:var(--dim)">HV%</span>=歷史波動率
</div>

<script>
let curC=0, curV='g', allD=null, prog=0;
const ldMsgs=['連接台灣期貨交易所...','拉取期貨現貨報價...','計算選擇權報價鏈...','計算 Greeks & IV...','處理完成！'];
const ldTimer=setInterval(()=>{
  prog=Math.min(prog+2,95);
  const bar=document.getElementById('ldbar');
  if(bar)bar.style.width=prog+'%';
  const txt=document.getElementById('ldtxt');
  if(txt)txt.textContent=ldMsgs[Math.min(Math.floor(prog/25),4)];
},500);

function setView(v){
  curV=v;
  document.querySelectorAll('.vb').forEach((b,i)=>b.classList.toggle('active',(i===0&&v==='g')||(i===1&&v==='m')));
  if(allD)render();
}
function setC(i){
  curC=i;
  document.querySelectorAll('.tb').forEach((b,j)=>b.classList.toggle('active',i===j));
  if(allD)render();
}

function fd(v,d){return(v===undefined||v===null||v===0)?'<span class="nd">--</span>':`<span>${typeof d==='number'?v.toFixed(d):v}</span>`}
function fDelta(v,c){
  if(!v)return'<span class="nd">--</span>';
  const a=Math.abs(v);
  const cl=c?(a>=.7?'dhi':a>=.4?'dmd':'dlo'):(a>=.7?'phi':a>=.4?'pmd':'plo');
  return`<span class="${cl}">${v.toFixed(4)}</span>`;
}
function fDiff(v){
  if(!v)return'<span class="nd">--</span>';
  return`<span class="${v>0?'du':'dd'}">${v>0?'▲':'▼'}${Math.abs(v)}</span>`;
}
function fIV(v){return v?`<span class="iv">${v.toFixed(2)}</span>`:'<span class="nd">--</span>';}
function fp(v,c){return v?`<span class="${c}">${v}</span>`:'<span class="nd">--</span>';}

function gHead(){
  return`<tr>
    <th colspan="6" class="ch" style="text-align:center">買權 Call</th>
    <th class="sh" style="text-align:center">履約價</th>
    <th colspan="6" class="ph" style="text-align:center">賣權 Put</th>
  </tr><tr>
    <th class="ch">Delta</th><th class="ch">Gamma</th><th class="ch">Theta</th>
    <th class="ch">Vega</th><th class="ch">Rho</th><th class="ch">成交</th>
    <th class="sh" style="text-align:center">Strike</th>
    <th class="ph">成交</th><th class="ph">Rho</th><th class="ph">Vega</th>
    <th class="ph">Theta</th><th class="ph">Gamma</th><th class="ph">Delta</th>
  </tr>`;
}
function mHead(){
  return`<tr>
    <th colspan="6" class="ch" style="text-align:center">買權 Call</th>
    <th class="sh" style="text-align:center">履約價</th>
    <th colspan="6" class="ph" style="text-align:center">賣權 Put</th>
  </tr><tr>
    <th class="ch">買進</th><th class="ch">賣出</th><th class="ch">成交</th>
    <th class="ch">漲跌</th><th class="ch">HV%</th><th class="ch">IV%</th>
    <th class="sh" style="text-align:center">Strike</th>
    <th class="ph">IV%</th><th class="ph">HV%</th><th class="ph">漲跌</th>
    <th class="ph">成交</th><th class="ph">賣出</th><th class="ph">買進</th>
  </tr>`;
}
function gRow(r,spot){
  const atm=Math.abs(r.strike-spot)<60,ic=r.strike<spot,ip=r.strike>spot;
  const cls=atm?'atm':ic?'ic':ip?'ip':'';
  return`<tr class="${cls}">
    <td class="cs">${fDelta(r.c_delta,true)}</td>
    <td class="cs"><span class="gv">${r.c_gamma?r.c_gamma.toFixed(5):'--'}</span></td>
    <td class="cs"><span class="tv2">${r.c_theta?r.c_theta.toFixed(1):'--'}</span></td>
    <td class="cs"><span class="vv">${r.c_vega?r.c_vega.toFixed(1):'--'}</span></td>
    <td class="cs"><span class="rv">${r.c_rho?r.c_rho.toFixed(3):'--'}</span></td>
    <td class="cs">${fp(r.c_last,'cl')}</td>
    <td class="sk">${r.strike}</td>
    <td class="ps">${fp(r.p_last,'pl')}</td>
    <td class="ps"><span class="rv">${r.p_rho?r.p_rho.toFixed(3):'--'}</span></td>
    <td class="ps"><span class="vv">${r.p_vega?r.p_vega.toFixed(1):'--'}</span></td>
    <td class="ps"><span class="tv2">${r.p_theta?r.p_theta.toFixed(1):'--'}</span></td>
    <td class="ps"><span class="gv">${r.p_gamma?r.p_gamma.toFixed(5):'--'}</span></td>
    <td class="ps">${fDelta(r.p_delta,false)}</td>
  </tr>`;
}
function mRow(r,spot,hv){
  const atm=Math.abs(r.strike-spot)<60,ic=r.strike<spot,ip=r.strike>spot;
  const cls=atm?'atm':ic?'ic':ip?'ip':'';
  const hvs=`<span class="hvc">${hv?hv.toFixed(2):'--'}</span>`;
  return`<tr class="${cls}">
    <td class="cs"><span class="cb">${r.c_bid||'--'}</span></td>
    <td class="cs"><span class="ca">${r.c_ask||'--'}</span></td>
    <td class="cs">${fp(r.c_last,'cl')}</td>
    <td class="cs">${fDiff(r.c_diff)}</td>
    <td class="cs">${hvs}</td>
    <td class="cs">${fIV(r.c_iv)}</td>
    <td class="sk">${r.strike}</td>
    <td class="ps">${fIV(r.p_iv)}</td>
    <td class="ps">${hvs}</td>
    <td class="ps">${fDiff(r.p_diff)}</td>
    <td class="ps">${fp(r.p_last,'pl')}</td>
    <td class="ps"><span class="pa">${r.p_ask||'--'}</span></td>
    <td class="ps"><span class="pb">${r.p_bid||'--'}</span></td>
  </tr>`;
}

function render(){
  if(!allD||!allD.contracts.length)return;
  const spot=allD.spot, hv=allD.hv;
  const con=allD.contracts[curC];
  if(!con)return;
  document.getElementById('db').textContent=`距到期 ${con.days_left} 天`;
  document.getElementById('ch').innerHTML=curV==='g'?gHead():mHead();
  let html='';
  (con.chain||[]).forEach(r=>{
    html+=curV==='g'?gRow(r,spot):mRow(r,spot,hv);
  });
  document.getElementById('cb').innerHTML=html;
  const atm=document.querySelector('.atm');
  if(atm&&!window._scrolled){window._scrolled=true;setTimeout(()=>atm.scrollIntoView({block:'center',behavior:'smooth'}),100);}
}

let _firstRender=true;
async function fetchData(){
  try{
    const r=await fetch('/api/chain');
    const d=await r.json();
    if(!d.ready)return;
    allD=d;
    document.getElementById('sv').textContent=d.spot?d.spot.toLocaleString('zh-TW',{minimumFractionDigits:2,maximumFractionDigits:2}):'--';
    document.getElementById('fv').textContent=d.fut?Math.round(d.fut).toLocaleString():'--';
    document.getElementById('hv').textContent=d.hv?d.hv.toFixed(2)+'%':'--%';
    if(d.hv_source)document.getElementById('hv-label').textContent=d.hv_source+' ';
    document.getElementById('tv').textContent=d.update_time||'--';
    // Tabs
    document.getElementById('tabs').innerHTML=d.contracts.map((c,i)=>
      `<button class="tb ${i===curC?'active':''}" onclick="setC(${i})">${c.label}</button>`
    ).join('');
    // First show
    if(_firstRender){
      _firstRender=false;
      clearInterval(ldTimer);
      document.getElementById('ldbar').style.width='100%';
      setTimeout(()=>{
        document.getElementById('ld').style.display='none';
        document.getElementById('ct').style.display='';
        render();
      },300);
    } else {
      render();
    }
  }catch(e){}
}

fetchData();
setInterval(fetchData,6000);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
