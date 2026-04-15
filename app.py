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

def is_market_open() -> bool:
    """判斷台灣期貨日盤是否開盤（只看日盤 08:45–13:45，不含夜盤）"""
    from datetime import timezone
    tz_tw = timezone(timedelta(hours=8))
    now = datetime.now(tz_tw)
    wd = now.weekday()  # 0=Mon 6=Sun
    if wd >= 5: return False                          # 週六/日收盤
    t = now.hour * 60 + now.minute
    return 8*60+45 <= t <= 13*60+45                  # 日盤 08:45–13:45

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
        days_left = (exp - today).days
        # 月選近月到期 ≤14 天時 TAIFEX 會新增 50 點區間履約價
        step = 50 if (found == 0 and days_left <= 14) else 100
        contracts.append({
            "label": f"{label} {yr}/{mo:02d}",
            "expiry": exp,
            "prefix": "TXO",
            "call_suffix": f"{CALL_MONTH_CODES[mo]}{yr%10}-O",
            "put_suffix":  f"{PUT_MONTH_CODES[mo]}{yr%10}-O",
            "strike_step": step,
        })
        found += 1
        if found >= 2: break

    # ── 週選: 最近 4 個週三選擇權 (TX1-TX5，跳過月選到期日) ──
    # TAIFEX 週三系列: TX1=第1週三, TX2=第2週三, TX4=第4週三, TX5=第5週三
    # 第3週三通常是月選到期日 (TXO)，不另列週選
    weekly_found = []
    check_d = today
    while len(weekly_found) < 4 and check_d <= today + timedelta(days=70):
        if check_d.weekday() == 2:  # Wednesday
            yr_c, mo_c = check_d.year, check_d.month
            # 計算是當月第幾個週三
            d_tmp, cnt = date(yr_c, mo_c, 1), 0
            while d_tmp <= check_d:
                if d_tmp.weekday() == 2: cnt += 1
                d_tmp += timedelta(days=1)
            # 跳過月選到期日（第3週三 = TXO 到期）
            if check_d == monthly_expiry(yr_c, mo_c):
                check_d += timedelta(days=1)
                continue
            if 1 <= cnt <= 5:
                prefix = f"TX{cnt}"
                weekly_found.append({
                    "label": f"週選W{cnt} {check_d.strftime('%m/%d')}",
                    "expiry": check_d,
                    "prefix": prefix,
                    "call_suffix": f"{CALL_MONTH_CODES[mo_c]}{yr_c%10}-O",
                    "put_suffix":  f"{PUT_MONTH_CODES[mo_c]}{yr_c%10}-O",
                    "strike_step": 50,
                })
        check_d += timedelta(days=1)

    contracts.extend(weekly_found)
    return contracts

# ─────────────────────────────────────────────
# TAIFEX API
# ─────────────────────────────────────────────
BASE = "https://mis.bq888.taifex.com.tw/futures/api/"
HDRS = {"User-Agent": "Mozilla/5.0"}

def _near_month_futures_sym(prefix="MXF") -> str:
    """取近月小台期貨 symbol，格式如 MXFD6-F（2026/04）"""
    today = date.today()
    yr, mo = today.year, today.month
    exp = monthly_expiry(yr, mo)
    if exp < today:          # 近月已到期，取次月
        mo += 1
        if mo > 12: yr += 1; mo = 1
    return f"{prefix}{CALL_MONTH_CODES[mo]}{yr%10}-F"

def fetch_underlying():
    """
    抓台指現貨（TXO-Q）與小台近月期貨（MXF）日盤即時報價。
    回傳 (spot, fut)，失敗時回傳 (0.0, 0.0)。
    """
    mxf_sym = _near_month_futures_sym("MXF")
    try:
        r = requests.post(BASE+"getQuoteDetail",
            json={"SymbolID":["TXO-Q", mxf_sym]},
            headers=HDRS, timeout=8, verify=False, allow_redirects=False)
        if r.status_code != 200:
            return 0.0, 0.0
        ql = r.json().get("RtData",{}).get("QuoteList",[])
        spot = fut = 0.0
        for q in ql:
            try: val = float(q.get("CLastPrice") or 0)
            except: val = 0.0
            sid = q.get("SymbolID","")
            if sid == "TXO-Q":    spot = val
            elif sid == mxf_sym:  fut  = val
        return spot, fut
    except: return 0.0, 0.0

def fetch_option_chain(contract, atm, wings=18):
    step = contract["strike_step"]
    atm_r = round(atm / step) * step
    # 月選用寬範圍（ATM -10000 ~ +6000），週選維持原本小範圍
    if wings == 18:  # 預設呼叫 → 依合約類型決定範圍
        if step == 100:   # 月選
            lo = atm_r - 10000
            hi = atm_r + 6000
        else:             # 週選 step=50
            lo = atm_r - 3000
            hi = atm_r + 2000
        strikes = list(range(lo, hi + step, step))
    else:
        strikes = [atm_r + i*step for i in range(-wings, wings+1)]

    call_syms = [f'{contract["prefix"]}{s}{contract["call_suffix"]}' for s in strikes]
    put_syms  = [f'{contract["prefix"]}{s}{contract["put_suffix"]}'  for s in strikes]
    all_syms  = call_syms + put_syms
    chain_data = {}
    # 正確分批（每批80個，處理任意數量）
    batch_size = 80
    for i in range(0, len(all_syms), batch_size):
        batch = all_syms[i:i+batch_size]
        try:
            r = requests.post(BASE+"getQuoteDetail",
                json={"SymbolID": batch},
                headers=HDRS, timeout=10, verify=False)
            for q in r.json().get("RtData",{}).get("QuoteList",[]):
                if q.get("SymbolID"): chain_data[q["SymbolID"]] = q
        except: pass
    rows = []
    for k, cs, ps in zip(strikes, call_syms, put_syms):
        cq = chain_data.get(cs, {})
        pq = chain_data.get(ps, {})
        # 過濾掉完全沒資料的履約價（參考價與成交價均空）
        if not cq.get("CRefPrice") and not pq.get("CRefPrice") \
                and not cq.get("CLastPrice") and not pq.get("CLastPrice"):
            continue
        rows.append({"strike":k, "call":cq, "put":pq})
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

def fetch_spot_yahoo() -> float:
    """市場收盤時從多個來源取台股加權指數最新收盤價"""
    # 來源1: Yahoo Finance
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII",
            params={"interval": "1d", "range": "5d"},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=10
        )
        if r.status_code == 200:
            result = r.json()["chart"]["result"][0]
            closes = [c for c in result["indicators"]["quote"][0].get("close", []) if c is not None]
            if closes:
                return round(float(closes[-1]), 2)
    except:
        pass
    # 來源2: Yahoo Finance v7
    try:
        r = requests.get(
            "https://query2.finance.yahoo.com/v8/finance/chart/%5ETWII",
            params={"interval": "1d", "range": "5d"},
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            timeout=10
        )
        if r.status_code == 200:
            result = r.json()["chart"]["result"][0]
            closes = [c for c in result["indicators"]["quote"][0].get("close", []) if c is not None]
            if closes:
                return round(float(closes[-1]), 2)
    except:
        pass
    # 來源3: TWSE 官方 API (台灣證交所)
    try:
        today = datetime.now().strftime("%Y%m%d")
        r = requests.get(
            f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
            params={"response": "json", "date": today, "type": "IND"},
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.twse.com.tw"},
            timeout=10
        )
        data = r.json()
        for row in data.get("data", []):
            if row and "發行量加權股價指數" in str(row):
                val = str(row[-2] if len(row) > 2 else row[-1]).replace(",", "")
                return round(float(val), 2)
    except:
        pass
    return 0.0

def _contract_csv_code(contract: dict) -> str:
    """把 get_active_contracts() 的 contract 轉換成 TAIFEX CSV 的契約代碼"""
    exp = contract["expiry"]
    yr, mo = exp.year, exp.month
    prefix = contract["prefix"]
    if prefix == "TXO":
        return f"{yr}{mo:02d}"
    elif prefix.startswith("TX") and len(prefix) == 3 and prefix[2].isdigit():
        # TX1~TX5 → 202604W1 ~ 202604W5
        n = prefix[2]
        return f"{yr}{mo:02d}W{n}"
    elif prefix == "TXV":
        # 數這個 expiry 是當月第幾個週五
        d, cnt = date(yr, mo, 1), 0
        while d <= exp:
            if d.weekday() == 4: cnt += 1
            d += timedelta(days=1)
        return f"{yr}{mo:02d}F{cnt}"
    return f"{yr}{mo:02d}"

def fetch_settlement_prices_from_csv() -> bool:
    """
    從 TAIFEX CSV 取最近交易日（含今天）的選擇權收盤價，
    填入 _last_live_prices 快取，讓收盤期間也能看到成交價。
    同時取 MTX 近月日盤收盤價與最後交易日日期，存入全域變數。
    從今天往前最多找 7 個交易日，CSV 沒資料就往前一天。
    回傳 True=成功，False=失敗
    """
    global _last_live_prices, _last_trading_date_str, _mtx_settlement_close, _settlement_loaded_date

    for delta in range(0, 10):
        d = date.today() - timedelta(days=delta)
        if d.weekday() >= 5:   # 跳過週六/日
            continue
        date_str = d.strftime("%Y/%m/%d")
        try:
            r = requests.get(
                "https://www.taifex.com.tw/cht/3/optDataDown",
                params={"down_type":"1","queryStartDate":date_str,
                        "queryEndDate":date_str,"commodity_id":"TXO"},
                headers={"User-Agent":"Mozilla/5.0",
                         "Referer":"https://www.taifex.com.tw/cht/3/optDailyMarketReport"},
                timeout=20, verify=False
            )
        except Exception as e:
            print(f"[settlement] fetch error {date_str}: {e}")
            continue

        if r.status_code != 200 or len(r.content) < 500:
            print(f"[settlement] no data for {date_str} (status={r.status_code} len={len(r.content)}), trying previous day")
            continue

        # 解析：col[8]=收盤價, col[9]=漲跌點數 → c_ref = c_last - c_diff
        raw: dict = {}
        for line in r.content.decode("ms950", errors="replace").strip().split("\n")[1:]:
            cols = [c.strip() for c in line.split(",")]
            if len(cols) < 18: continue
            if cols[17].strip() != "一般": continue
            csv_code = cols[2].strip()
            try:
                k     = int(float(cols[3].replace(".0000","").strip()))
                close = float(cols[8]) if cols[8] not in ("-","") else 0.0
                diff  = float(cols[9]) if cols[9] not in ("-","") else 0.0
            except (ValueError, TypeError):
                continue
            side = cols[4].strip()
            if csv_code not in raw:
                raw[csv_code] = {}
            if k not in raw[csv_code]:
                raw[csv_code][k] = {"c_last":0,"c_ref":0,"p_last":0,"p_ref":0}
            if "買" in side:
                raw[csv_code][k]["c_last"] = int(close)
                raw[csv_code][k]["c_ref"]  = int(close - diff)
            else:
                raw[csv_code][k]["p_last"] = int(close)
                raw[csv_code][k]["p_ref"]  = int(close - diff)

        if not raw:
            print(f"[settlement] parsed empty for {date_str}, trying previous day")
            continue

        # 有資料 → 記錄最後交易日
        _last_trading_date_str = d.strftime("%Y/%m/%d")
        contracts_meta = get_active_contracts()
        new_cache: dict = {}
        for c in contracts_meta:
            csv_code = _contract_csv_code(c)
            if csv_code in raw:
                new_cache[c["label"]] = raw[csv_code]
        if new_cache:
            with _lock:
                for label, prices in new_cache.items():
                    if label not in _last_live_prices:
                        _last_live_prices[label] = {}
                    _last_live_prices[label].update(prices)
        print(f"[settlement] loaded {d} prices for {list(new_cache.keys())}")

        # 順便抓 MTX 近月日盤收盤價
        try:
            r2 = requests.get(
                "https://www.taifex.com.tw/cht/3/futDataDown",
                params={"down_type":"1","queryStartDate":date_str,
                        "queryEndDate":date_str,"commodity_id":"MTX"},
                headers={"User-Agent":"Mozilla/5.0",
                         "Referer":"https://www.taifex.com.tw/cht/3/futDailyMarketReport"},
                timeout=15, verify=False
            )
            if r2.status_code == 200 and len(r2.content) > 200:
                lines2 = r2.content.decode("ms950", errors="replace").strip().split("\n")
                best_vol2, best_close2 = 0, 0.0
                for line2 in lines2[1:]:
                    cols2 = [c.strip() for c in line2.split(",")]
                    if len(cols2) < 18: continue
                    if cols2[17].strip() != "一般": continue
                    try:
                        vol2   = int(cols2[9].replace(",","") or "0")
                        close2 = float(cols2[6].replace(",","") or "0")
                        if vol2 > best_vol2 and vol2 > 0 and close2 > 0:
                            best_vol2   = vol2
                            best_close2 = close2
                    except (ValueError, IndexError):
                        continue
                if best_close2 > 0:
                    _mtx_settlement_close = best_close2
                    print(f"[settlement] MTX close={best_close2} on {date_str}")
        except Exception as e2:
            print(f"[settlement] MTX error: {e2}")

        _settlement_loaded_date = d
        return True

    print("[settlement] failed: no CSV data found in past 10 days")
    return False

def fetch_ref_prices(contract: dict, strikes: list) -> dict:
    """
    收盤時從 TAIFEX API 取各履約價的參考價（CRefPrice）與最後成交（CLastPrice）。
    回傳 {symbol_id: {"last": float, "ref": float}} 字典。
    失敗時回傳空 dict，不影響主流程。
    """
    call_syms = [f'{contract["prefix"]}{k}{contract["call_suffix"]}' for k in strikes]
    put_syms  = [f'{contract["prefix"]}{k}{contract["put_suffix"]}'  for k in strikes]
    result = {}
    for batch in [call_syms[:40] + put_syms[:40], call_syms[40:] + put_syms[40:]]:
        if not batch:
            continue
        try:
            r = requests.post(BASE + "getQuoteDetail",
                json={"SymbolID": batch},
                headers=HDRS, timeout=10, verify=False)
            if r.status_code != 200:
                continue
            for q in r.json().get("RtData", {}).get("QuoteList", []):
                sid = q.get("SymbolID")
                if not sid:
                    continue
                def _f(key):
                    try: return float(q.get(key) or 0)
                    except: return 0.0
                result[sid] = {"last": _f("CLastPrice"), "ref": _f("CRefPrice")}
        except:
            pass
    return result

def build_chain_data_closed(contract: dict, spot: float, hv: float) -> list:
    """
    市場收盤時的選擇權鏈：
    - Greeks 用 BS 純計算
    - 成交價 / 參考價：嘗試從 TAIFEX API 取 CLastPrice / CRefPrice
    """
    T = time_to_expiry_years(contract["expiry"])
    step = contract["strike_step"]
    atm_r = round(spot / step) * step
    sigma = max(hv, 10.0) / 100

    strikes = [atm_r + i * step for i in range(-18, 19)]
    call_syms = [f'{contract["prefix"]}{k}{contract["call_suffix"]}' for k in strikes]
    put_syms  = [f'{contract["prefix"]}{k}{contract["put_suffix"]}'  for k in strikes]

    # 讀取上次開盤時的成交價快取
    live_cache = _last_live_prices.get(contract["label"], {})

    result = []
    for k in strikes:
        cg = bs_greeks(spot, k, T, RISK_FREE_RATE, sigma, True)
        pg = bs_greeks(spot, k, T, RISK_FREE_RATE, sigma, False)
        cached = live_cache.get(k, {})
        c_last = cached.get("c_last", 0)
        c_ref  = cached.get("c_ref",  0)
        p_last = cached.get("p_last", 0)
        p_ref  = cached.get("p_ref",  0)
        result.append({
            "strike": k,
            "c_bid":0,"c_ask":0,"c_last":c_last,"c_ref":c_ref,"c_diff":0,"c_iv":None,
            "c_delta":round(cg.get("delta",0),4),"c_gamma":round(cg.get("gamma",0),6),
            "c_theta":round(cg.get("theta",0),2),"c_vega":round(cg.get("vega",0),2),
            "c_rho":round(cg.get("rho",0),4),
            "p_bid":0,"p_ask":0,"p_last":p_last,"p_ref":p_ref,"p_diff":0,"p_iv":None,
            "p_delta":round(pg.get("delta",0),4),"p_gamma":round(pg.get("gamma",0),6),
            "p_theta":round(pg.get("theta",0),2),"p_vega":round(pg.get("vega",0),2),
            "p_rho":round(pg.get("rho",0),4),
        })
    return result

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
_cache = {"spot":0.0,"fut":0.0,"hv":25.0,"update_time":"--","data_date":"--","contracts":[], "ready":False, "market_status":"--"}
_lock  = threading.Lock()
_hv_last_fetch = 0.0
_hv_value = 25.0
_last_error = ""
_refresh_log = []
# 最後一次開盤時各合約的成交價快取 {contract_label: {strike: {"c_last":x, "p_last":x}}}
_last_live_prices: dict = {}
# 最後一個交易日資訊（由 fetch_settlement_prices_from_csv 填入）
_last_trading_date_str = "--"   # e.g. "04/10"
_mtx_settlement_close  = 0.0   # MTX 近月合約日盤收盤價
_settlement_loaded_date = None  # 已成功載入結算價的日期（date 物件）

def build_chain_data(contract, spot, hv, compute_atm=False):
    global _last_live_prices
    T = time_to_expiry_years(contract["expiry"])
    rows = fetch_option_chain(contract, spot)
    if compute_atm and hv <= 0:
        hv = compute_atm_iv(spot, contract, rows) or 25.0
    result = []
    price_cache = {}   # 本次快取，結束後一次寫入 _last_live_prices
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
        # 有成交價才存進快取（避免沒成交的合約覆蓋舊資料）
        if c_last > 0 or p_last > 0:
            price_cache[k] = {
                "c_last": int(c_last), "c_ref": int(c_ref),
                "p_last": int(p_last), "p_ref": int(p_ref),
            }
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
    # 更新全域快取（只更新有成交的合約）
    label = contract["label"]
    if price_cache:
        if label not in _last_live_prices:
            _last_live_prices[label] = {}
        _last_live_prices[label].update(price_cache)
    return result

def refresh_loop():
    import traceback as _tb
    global _hv_last_fetch, _hv_value, _last_error, _refresh_log, _settlement_loaded_date
    _refresh_log = [f"THREAD_STARTED_AT:{datetime.now().isoformat()}"]
    print(f"[refresh_loop] started pid={os.getpid()} tid={threading.current_thread().ident}")
    # 啟動時預載最近交易日收盤價（讓收盤期間立刻有成交價可看）
    fetch_settlement_prices_from_csv()
    while True:
        try:
            interval = 6
            log = []
            try:
                market_open = is_market_open()
                log.append(f"step1:market_open={market_open}")

                spot = fut = 0.0
                if market_open:
                    spot, fut = fetch_underlying()
                log.append(f"step1_done:spot={spot}")

                if spot <= 0 or not market_open:
                    # 收盤：若今日結算價尚未載入，嘗試重新抓取（每 300s 最多一次）
                    today_d = date.today()
                    if _settlement_loaded_date != today_d:
                        log.append("step1b:re_fetch_settlement")
                        fetch_settlement_prices_from_csv()
                        log.append(f"step1b_done:loaded={_settlement_loaded_date}")
                    # 收盤：用 Yahoo Finance 取最新收盤價
                    if spot <= 0:
                        log.append("step2:fetch_yahoo")
                        spot = fetch_spot_yahoo()
                        log.append(f"step2_done:spot={spot}")
                    # fut 用最後交易日 MTX 收盤價，抓不到才退回 spot
                    fut = _mtx_settlement_close if _mtx_settlement_close > 0 else spot
                    market_status = "收盤"
                    interval = 300
                    if spot <= 0:
                        log.append("step2_fail:spot=0")
                        _refresh_log = log
                        time.sleep(60)
                        continue
                else:
                    market_status = "即時"

                log.append("step3:hv")
                if time.time() - _hv_last_fetch > 3600:
                    _hv_value = fetch_hv_local() or 0.0
                    _hv_last_fetch = time.time()
                hv = _hv_value or 25.0
                log.append(f"step3_done:hv={hv}")

                log.append("step4:get_contracts")
                contracts_meta = get_active_contracts()
                log.append(f"step4_done:n={len(contracts_meta)}")

                results = []
                for ci, c in enumerate(contracts_meta):
                    log.append(f"step5_{ci}:build:{c['label'][:8]}")
                    if market_status == "收盤":
                        chain = build_chain_data_closed(c, spot, hv)
                    else:
                        chain = build_chain_data(c, spot, hv, compute_atm=(ci==0 and hv<=0))
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
                    log.append(f"step5_{ci}_done:rows={len(chain)}")

                log.append("step6:update_cache")
                hv_source = "HV" if fetch_hv_local() else "ATM-IV"
                now_tw = datetime.now()
                with _lock:
                    _cache.update({
                        "spot": spot, "fut": fut, "hv": hv, "hv_source": hv_source,
                        "update_time": now_tw.strftime("%H:%M:%S"),
                        "data_date":   now_tw.strftime("%Y/%m/%d") if market_status == "即時" else _last_trading_date_str,
                        "contracts": results, "ready": True,
                        "market_status": market_status,
                    })
                log.append("step6_done:ready=True")
                _refresh_log = log
            except Exception as e:
                _last_error = _tb.format_exc()
                log.append(f"EXCEPTION:{e}")
                _refresh_log = log
                print(f"[refresh error] {_last_error}")
                interval = 30
            time.sleep(interval)
        except BaseException as e:
            # 捕捉 SystemExit/KeyboardInterrupt 等，防止 thread 死亡
            _last_error = f"BaseException:{_tb.format_exc()}"
            print(f"[refresh FATAL] {e}")
            try: time.sleep(10)
            except: pass

# ─────────────────────────────────────────────
# Flask App
# ─────────────────────────────────────────────
app = Flask(__name__)

def _start_refresh_thread():
    t = threading.Thread(target=refresh_loop, daemon=True, name="refresh")
    t.start()
    print(f"[_start_refresh_thread] started, alive={t.is_alive()} pid={os.getpid()}")
    return t

# 延遲啟動：在第一個 HTTP request 到來後才啟動（避免 gunicorn fork 後 thread 消失）
_refresh_thread = None
_thread_start_lock = threading.Lock()

def _ensure_refresh_thread():
    global _refresh_thread
    with _thread_start_lock:
        if _refresh_thread is None or not _refresh_thread.is_alive():
            _refresh_thread = _start_refresh_thread()

def _watchdog():
    """監控 refresh_thread，若死亡則重啟"""
    global _refresh_thread
    while True:
        time.sleep(30)
        if _refresh_thread is None or not _refresh_thread.is_alive():
            print("[watchdog] refresh_thread died, restarting...")
            _ensure_refresh_thread()

_watchdog_thread = threading.Thread(target=_watchdog, daemon=True, name="watchdog")
_watchdog_thread.start()

@app.before_request
def _lazy_start():
    _ensure_refresh_thread()

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">
  <rect width="192" height="192" rx="36" fill="#0d1117"/>
  <!-- vertical pole -->
  <rect x="89" y="56" width="14" height="118" rx="5" fill="#1d3557"/>
  <!-- base stand -->
  <rect x="63" y="166" width="66" height="12" rx="6" fill="#1d3557"/>
  <!-- beam -->
  <rect x="14" y="44" width="164" height="16" rx="8" fill="#1d3557"/>
  <!-- pivot cap -->
  <circle cx="96" cy="44" r="10" fill="#1d3557"/>
  <!-- left chains (V from beam-tip to top of left circle) -->
  <!-- left circle: cx=40 cy=115 r=29, top at y=86 -->
  <line x1="22" y1="52" x2="14" y2="89" stroke="#1d3557" stroke-width="5" stroke-linecap="round"/>
  <line x1="22" y1="52" x2="64" y2="89" stroke="#1d3557" stroke-width="5" stroke-linecap="round"/>
  <!-- left pan plate -->
  <rect x="11" y="141" width="58" height="8" rx="4" fill="#1d3557"/>
  <!-- left C circle -->
  <circle cx="40" cy="115" r="29" fill="#c0392b"/>
  <text x="40" y="126" text-anchor="middle" dominant-baseline="middle"
        fill="white" font-size="32" font-weight="bold"
        font-family="Arial,Helvetica,sans-serif">C</text>
  <!-- right chains (V from beam-tip to top of right circle) -->
  <!-- right circle: cx=152 cy=115 r=29, top at y=86 -->
  <line x1="170" y1="52" x2="178" y2="89" stroke="#1d3557" stroke-width="5" stroke-linecap="round"/>
  <line x1="170" y1="52" x2="128" y2="89" stroke="#1d3557" stroke-width="5" stroke-linecap="round"/>
  <!-- right pan plate -->
  <rect x="123" y="141" width="58" height="8" rx="4" fill="#1d3557"/>
  <!-- right P circle -->
  <circle cx="152" cy="115" r="29" fill="#27ae60"/>
  <text x="152" y="126" text-anchor="middle" dominant-baseline="middle"
        fill="white" font-size="32" font-weight="bold"
        font-family="Arial,Helvetica,sans-serif">P</text>
</svg>"""

MANIFEST_JSON = """{
  "name": "NightGod 台指選擇權",
  "short_name": "NightGod 台指選擇權",
  "description": "台指選擇權即時監控",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0d1117",
  "theme_color": "#0d1117",
  "icons": [
    {"src": "/icon.svg?v=3", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}
  ]
}"""

@app.route("/icon.svg")
def serve_icon():
    from flask import Response
    return Response(ICON_SVG, mimetype="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})

@app.route("/manifest.json")
def serve_manifest():
    from flask import Response
    return Response(MANIFEST_JSON, mimetype="application/manifest+json")

@app.route("/api/chain")
def api_chain():
    with _lock:
        if not _cache["ready"]:
            return jsonify({"ready": False})
        return jsonify({
            "ready":True,
            "spot":_cache["spot"], "fut":_cache["fut"],
            "hv":_cache["hv"], "update_time":_cache["update_time"],
            "data_date": _cache.get("data_date","--"),
            "contracts":_cache["contracts"],
            "market_status": _cache.get("market_status", "即時"),
        })

@app.route("/health")
def health():
    return "ok", 200

@app.route("/debug")
def debug():
    """診斷端點：直接執行一次完整流程並回傳結果"""
    result = {"steps": []}
    def log(msg): result["steps"].append(msg)

    try:
        log("1:fetch_underlying")
        spot, fut = fetch_underlying()
        log(f"1_done: spot={spot}")

        if spot <= 0:
            log("2:fetch_spot_yahoo")
            spot = fetch_spot_yahoo()
            log(f"2_done: spot={spot}")

        log(f"3:get_contracts")
        contracts = get_active_contracts()
        log(f"3_done: n={len(contracts)} labels={[c['label'] for c in contracts]}")

        if spot > 0 and contracts:
            log("4:build_chain_closed (first contract)")
            chain = build_chain_data_closed(contracts[0], spot, 25.0)
            log(f"4_done: rows={len(chain)}")

        result["cache_ready"] = _cache["ready"]
        result["cache_market_status"] = _cache.get("market_status")
        result["last_error"] = _last_error
        result["refresh_log"] = _refresh_log
        result["thread_alive"] = _refresh_thread.is_alive() if _refresh_thread else False
        result["thread_name"] = _refresh_thread.name if _refresh_thread else None
        result["pid"] = os.getpid()
        result["is_market_open"] = is_market_open()
    except Exception as e:
        import traceback
        result["exception"] = traceback.format_exc()

    return jsonify(result)

HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="NightGod 台指選擇權">
<meta name="theme-color" content="#0d1117">
<title>NightGod 台指選擇權</title>
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icon.svg">
<link rel="icon" type="image/svg+xml" href="/icon.svg">
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
.dot-closed{display:inline-block;width:7px;height:7px;border-radius:50%;
            background:var(--dim);margin-right:4px}
.dot-night{display:inline-block;width:7px;height:7px;border-radius:50%;
           background:var(--yel);animation:pulse 2s infinite;margin-right:4px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.status-badge{font-size:10px;padding:1px 6px;border-radius:8px;margin-left:4px}
.status-live{background:#1a3a2a;color:var(--green)}
.status-closed{background:#1e1e1e;color:var(--dim)}
.status-night{background:#2a2a10;color:var(--yel)}

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
.cu{color:var(--red);font-weight:bold}.cd{color:var(--green);font-weight:bold}.cn{font-weight:bold}
.cb{color:#ffaaaa}.ca{color:#ffaaaa}.pb{color:#aaddff}.pa{color:#aaddff}
.du{color:var(--red)}.dd{color:var(--green)}
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
    <div><span class="pl" id="date-label">-- </span><span class="pl">現貨 </span><span class="pv sv" id="sv">--</span></div>
    <div><span class="pl">小台 </span><span class="pv fv" id="fv">--</span></div>
    <div><span class="pl" id="hv-label">HV </span><span class="pv hv" id="hv">--%</span></div>
    <div class="tv"><span id="dot" class="dot-live"></span><span id="tv">--:--:--</span><span id="msbadge" class="status-badge"></span></div>
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
const ldMsgs=['連接台灣期貨交易所...','拉取現貨報價...','計算選擇權報價鏈...','計算 Greeks & IV...','處理完成！'];
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
function fp(v,ref){
  if(!v)return'<span class="nd">--</span>';
  const cls=ref>0?(v>ref?'cu':v<ref?'cd':'cn'):'cn';
  return`<span class="${cls}">${v}</span>`;
}

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
function gRow(r,spot,atmStrike){
  const atm=r.strike===atmStrike,ic=r.strike<spot,ip=r.strike>spot;
  const cls=atm?'atm':ic?'ic':ip?'ip':'';
  return`<tr class="${cls}">
    <td class="cs">${fDelta(r.c_delta,true)}</td>
    <td class="cs"><span class="gv">${r.c_gamma?r.c_gamma.toFixed(5):'--'}</span></td>
    <td class="cs"><span class="tv2">${r.c_theta?r.c_theta.toFixed(1):'--'}</span></td>
    <td class="cs"><span class="vv">${r.c_vega?r.c_vega.toFixed(1):'--'}</span></td>
    <td class="cs"><span class="rv">${r.c_rho?r.c_rho.toFixed(3):'--'}</span></td>
    <td class="cs">${fp(r.c_last,r.c_ref)}</td>
    <td class="sk">${r.strike}</td>
    <td class="ps">${fp(r.p_last,r.p_ref)}</td>
    <td class="ps"><span class="rv">${r.p_rho?r.p_rho.toFixed(3):'--'}</span></td>
    <td class="ps"><span class="vv">${r.p_vega?r.p_vega.toFixed(1):'--'}</span></td>
    <td class="ps"><span class="tv2">${r.p_theta?r.p_theta.toFixed(1):'--'}</span></td>
    <td class="ps"><span class="gv">${r.p_gamma?r.p_gamma.toFixed(5):'--'}</span></td>
    <td class="ps">${fDelta(r.p_delta,false)}</td>
  </tr>`;
}
function mRow(r,spot,hv,atmStrike){
  const atm=r.strike===atmStrike,ic=r.strike<spot,ip=r.strike>spot;
  const cls=atm?'atm':ic?'ic':ip?'ip':'';
  const hvs=`<span class="hvc">${hv?hv.toFixed(2):'--'}</span>`;
  return`<tr class="${cls}">
    <td class="cs"><span class="cb">${r.c_bid||'--'}</span></td>
    <td class="cs"><span class="ca">${r.c_ask||'--'}</span></td>
    <td class="cs">${fp(r.c_last,r.c_ref)}</td>
    <td class="cs">${fDiff(r.c_diff)}</td>
    <td class="cs">${hvs}</td>
    <td class="cs">${fIV(r.c_iv)}</td>
    <td class="sk">${r.strike}</td>
    <td class="ps">${fIV(r.p_iv)}</td>
    <td class="ps">${hvs}</td>
    <td class="ps">${fDiff(r.p_diff)}</td>
    <td class="ps">${fp(r.p_last,r.p_ref)}</td>
    <td class="ps"><span class="pa">${r.p_ask||'--'}</span></td>
    <td class="ps"><span class="pb">${r.p_bid||'--'}</span></td>
  </tr>`;
}

function render(){
  if(!allD||!allD.contracts.length)return;
  const spot=allD.spot, hv=allD.hv;
  const con=allD.contracts[curC];
  if(!con)return;
  // 找距離 spot 最近的單一履約價作為價平
  let atmStrike=null,minD=Infinity;
  (con.chain||[]).forEach(r=>{const d=Math.abs(r.strike-spot);if(d<minD){minD=d;atmStrike=r.strike;}});
  document.getElementById('db').textContent=`距到期 ${con.days_left} 天`;
  document.getElementById('ch').innerHTML=curV==='g'?gHead():mHead();
  let html='';
  (con.chain||[]).forEach(r=>{
    html+=curV==='g'?gRow(r,spot,atmStrike):mRow(r,spot,hv,atmStrike);
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
    if(d.data_date&&d.data_date!='--')document.getElementById('date-label').textContent=d.data_date+' ';
    // Market status dot & badge
    const ms=d.market_status||'即時';
    const dot=document.getElementById('dot');
    const badge=document.getElementById('msbadge');
    if(ms==='收盤'){
      dot.className='dot-closed';
      badge.className='status-badge status-closed';
      badge.textContent='收盤';
    } else if(ms==='夜盤'){
      dot.className='dot-night';
      badge.className='status-badge status-night';
      badge.textContent='夜盤';
    } else {
      dot.className='dot-live';
      badge.className='status-badge status-live';
      badge.textContent='即時';
    }
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
    from flask import make_response
    resp = make_response(render_template_string(HTML))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
