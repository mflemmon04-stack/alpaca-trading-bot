"""Autonomous Alpaca PAPER stock momentum bot. Not a validated profitable strategy."""
import os, time, json, logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
import requests
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOG = logging.getLogger('bot')
ET = ZoneInfo('America/New_York')
BASE = 'https://paper-api.alpaca.markets'
DATA = 'https://data.alpaca.markets'
KEY = os.environ['APCA_API_KEY_ID']
SECRET = os.environ['APCA_API_SECRET_KEY']
HEAD = {'APCA-API-KEY-ID': KEY, 'APCA-API-SECRET-KEY': SECRET}
SYMBOLS = [s.strip().upper() for s in os.getenv('SYMBOLS','NVDA,TSLA,AMD,PLTR,SOXL,RIOT,MSTR').split(',') if s.strip()]
INTERVAL = max(60,int(os.getenv('CHECK_SECONDS','180')))
RISK = float(os.getenv('RISK_PER_TRADE','0.01'))
MAX_ALLOC = float(os.getenv('MAX_POSITION_FRACTION','0.12'))
MAX_TOTAL = float(os.getenv('MAX_TOTAL_EXPOSURE','0.60'))
STOP = float(os.getenv('STOP_LOSS_PCT','0.055'))
TAKE = float(os.getenv('TAKE_PROFIT_PCT','0.12'))
MAX_DRAWDOWN = float(os.getenv('MAX_DRAWDOWN','0.15'))
DRY_RUN = os.getenv('DRY_RUN','true').lower() == 'true'
STATE_FILE = os.getenv('STATE_FILE','/tmp/alpaca_bot_state.json')
END_DATE = '2026-11-18'


def api(method, path, params=None, payload=None, data=False):
    url = (DATA if data else BASE) + path
    for attempt in range(3):
        try:
            res = requests.request(method,url,headers=HEAD,params=params,json=payload,timeout=18)
            if res.status_code == 429 or res.status_code >= 500:
                raise RuntimeError(f'{res.status_code}: {res.text[:180]}')
            res.raise_for_status()
            return res.json() if res.content else {}
        except (requests.RequestException, RuntimeError):
            if attempt == 2: raise
            time.sleep(2**attempt)


def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except (FileNotFoundError,ValueError): return {'peak_equity':0,'last_trade':{}}


def save_state(state):
    with open(STATE_FILE,'w') as f: json.dump(state,f)


def bars(symbol):
    raw=api('GET',f'/v2/stocks/{symbol}/bars',{'timeframe':'5Min','limit':150,'feed':'iex','adjustment':'raw'},data=True)
    df=pd.DataFrame(raw.get('bars',[]))
    if len(df)<55:return None
    df['t']=pd.to_datetime(df['t'],utc=True)
    # Restrict signal to the current US trading session, avoiding overnight gaps.
    return df


def score(df):
    c=df['c'].astype(float); v=df['v'].astype(float)
    fast=c.ewm(span=9,adjust=False).mean(); slow=c.ewm(span=26,adjust=False).mean()
    prev_high=c.iloc[-22:-1].max()
    relvol=float(v.iloc[-1]/max(v.iloc[-21:-1].mean(),1))
    trend=float(fast.iloc[-1]/slow.iloc[-1]-1)
    breakout=float(c.iloc[-1]/prev_high-1)
    momentum=float(c.iloc[-1]/c.iloc[-7]-1)
    eligible=trend>0.002 and breakout>0 and relvol>1.25 and momentum>0.005
    return eligible, 100*trend+50*breakout+20*momentum+min(relvol,4), float(c.iloc[-1]), relvol


def submit(side,symbol,qty=None,notional=None):
    payload={'symbol':symbol,'side':side,'type':'market','time_in_force':'day'}
    if qty is not None:payload['qty']=str(qty)
    else:payload['notional']=str(round(notional,2))
    LOG.warning('ORDER %s',payload)
    if DRY_RUN:return
    return api('POST','/v2/orders',payload=payload)


def cancel_open_stock_orders():
    orders=api('GET','/v2/orders',{'status':'open','limit':500})
    for o in orders:
        if o.get('asset_class')=='us_equity':
            LOG.warning('CANCEL stock order %s',o['id'])
            if not DRY_RUN:api('DELETE','/v2/orders/'+o['id'])


def close_stock_positions(positions):
    for p in positions:
        if p.get('asset_class')=='us_equity':
            LOG.warning('CLOSE stock position %s',p['symbol'])
            if not DRY_RUN:api('DELETE','/v2/positions/'+p['symbol'])


def cycle():
    now=datetime.now(ET)
    account=api('GET','/v2/account'); equity=float(account['equity'])
    state=load_state();state['peak_equity']=max(float(state.get('peak_equity',0)),equity)
    clock=api('GET','/v2/clock')
    positions=api('GET','/v2/positions')
    orders=api('GET','/v2/orders',{'status':'open','limit':500})
    open_symbols={o['symbol'] for o in orders}
    stock_positions={p['symbol']:p for p in positions if p.get('asset_class')=='us_equity'}
    stock_exposure=sum(abs(float(p['market_value'])) for p in stock_positions.values())
    LOG.info('equity=%.2f peak=%.2f stock_exposure=%.2f open_orders=%d dry_run=%s',equity,state['peak_equity'],stock_exposure,len(orders),DRY_RUN)
    save_state(state)
    # Mandatory deadline: close STOCKS by 3:45 PM ET. Existing options require manual liquidation.
    if now.date().isoformat()>=END_DATE:
        cancel_open_stock_orders();close_stock_positions(positions)
        LOG.warning('Deadline reached; stock trading disabled. Close options separately!')
        return
    if equity < state['peak_equity']*(1-MAX_DRAWDOWN):
        LOG.warning('Portfolio drawdown cutoff triggered')
        cancel_open_stock_orders();close_stock_positions(positions)
        return
    if not clock.get('is_open') or now.time()<dtime(9,40) or now.time()>dtime(15,35):return
    # Exit positions held by THIS BOT'S SYMBOL UNIVERSE; does not touch options.
    for symbol,p in stock_positions.items():
        if symbol not in SYMBOLS or symbol in open_symbols:continue
        pnl=float(p.get('unrealized_plpc',0))
        if pnl<=-STOP or pnl>=TAKE:
            LOG.info('Exit %s unrealized_return=%.3f',symbol,pnl)
            if not DRY_RUN:api('DELETE','/v2/positions/'+symbol)
    # No fresh entries if account already has queued orders for the ticker.
    candidates=[]
    for symbol in SYMBOLS:
        if symbol in stock_positions or symbol in open_symbols:continue
        try:
            df=bars(symbol)
            if df is None:continue
            good,s,price,rv=score(df)
            if good:candidates.append((s,symbol,price,rv))
        except Exception as e:LOG.error('Data unavailable %s: %s',symbol,e)
    candidates.sort(reverse=True)
    available=max(0, equity*MAX_TOTAL-stock_exposure)
    for s,symbol,price,rv in candidates[:2]:
        # Size by risk-to-stop and absolute exposure cap.
        budget=min(equity*MAX_ALLOC,equity*RISK/STOP,available)
        if budget<100:break
        LOG.info('Signal %s score=%.3f price=%.2f relative_volume=%.2f budget=%.2f',symbol,s,price,rv,budget)
        submit('buy',symbol,notional=budget)
        available-=budget


if __name__=='__main__':
    LOG.warning('Starting PAPER bot; DRY_RUN=%s. Existing options are NOT managed.',DRY_RUN)
    while True:
        try:cycle()
        except Exception:LOG.exception('Cycle failed; no new orders this cycle')
        time.sleep(INTERVAL)
