"""Transparent Kalshi Sniper-style research model. PAPER TRADING ONLY."""
import os, json, time, math, sqlite3, logging
from datetime import datetime, timezone
from statistics import pstdev
import requests

KALSHI = 'https://api.elections.kalshi.com/trade-api/v2'
DB = os.environ.get('SNIPER_DB', 'sniper_paper.db')
UA = {'User-Agent':'BTC-SignalLab-Paper/1.0'}

DEFAULT = dict(poll_seconds=12, bankroll=500., stake_usd=15., max_exposure=40., max_daily_loss=35., min_seconds=45, max_seconds=650,
    min_price=.16,max_price=.84,minimum_edge=.055,minimum_votes=6,minimum_confidence=.60, max_spread=.10, max_trades_day=12,
    tp_cents=14,sl_cents=12, max_hold_seconds=480, slippage_cents=1.0, futures_enabled=True, signal_cooldown=120)

def db():
    c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, ticker TEXT, side TEXT, quantity INT, entry REAL, entry_fee REAL, entry_ts REAL, exit REAL, exit_fee REAL, exit_ts REAL, pnl REAL, status TEXT, reason TEXT, signal_json TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS snapshots (ts REAL, ticker TEXT, spot REAL, strike REAL, yes_bid REAL, yes_ask REAL, no_bid REAL, no_ask REAL, probability REAL, confidence REAL, signals TEXT)')
    c.commit(); return c

def get(url, params=None, timeout=7):
    r=requests.get(url,params=params,headers=UA,timeout=timeout);r.raise_for_status();return r.json()

def price(x,default=None):
    try:
        if x is None or x=='': return default
        return float(x)
    except (ValueError,TypeError):return default

def ts(iso):
    if not iso:return 0
    try:return datetime.fromisoformat(iso.replace('Z','+00:00')).timestamp()
    except Exception:return 0

def market():
    data=get(KALSHI+'/markets',{'series_ticker':'KXBTC15M','status':'open','limit':100})
    now=time.time(); markets=[m for m in data.get('markets',[]) if m.get('ticker','').startswith('KXBTC15M-') and ts(m.get('close_time'))>now]
    markets.sort(key=lambda m: ts(m.get('close_time')))
    return markets[0] if markets else None

def book(ticker):
    d=get(KALSHI+'/markets/'+ticker+'/orderbook', {'depth':20}).get('orderbook_fp')
    if d is None:
        d=get(KALSHI+'/markets/'+ticker+'/orderbook', {'depth':20}).get('orderbook',{})
    def levels(side):
        ans=[]
        for row in d.get(side,[]):
            try:
                p=float(row[0]);sz=float(row[1]);
                if p>1:p/=100.
                if 0<p<1 and sz>0:ans.append((p,sz))
            except Exception:pass
        return sorted(ans,reverse=True)
    return levels('yes'),levels('no')

def spot_candles():
    # Coinbase public 1-minute candles; ensure candles are timestamp-ordered and current.
    candles=get('https://api.exchange.coinbase.com/products/BTC-USD/candles',{'granularity':60})
    candles=sorted(candles,key=lambda x:x[0])[-75:]
    return [{'t':v[0], 'low':float(v[1]),'high':float(v[2]),'open':float(v[3]),'close':float(v[4]),'vol':float(v[5])} for v in candles]

def futures():
    # Binance US geo restrictions may block this. In that case return None; never fabricate.
    try:
        base='https://fapi.binance.com'
        oi=get(base+'/fapi/v1/openInterest',{'symbol':'BTCUSDT'},timeout=4)
        premium=get(base+'/fapi/v1/premiumIndex',{'symbol':'BTCUSDT'},timeout=4)
        return {'oi':float(oi['openInterest']), 'funding':float(premium.get('lastFundingRate',0)), 'mark':float(premium['markPrice']), 'index':float(premium['indexPrice'])}
    except Exception:return None

def fee(p,q):
    # Approximate standard taker-fee formula rounded up per order; fee schedules can change.
    return math.ceil(max(0,.07*q*p*(1-p))*100-1e-8)/100

def sigmoid(x):return 1/(1+math.exp(-max(-30,min(30,x))))

def compute(candles, m, yes_bid,yes_ask,no_bid,no_ask, futures_now=None, futures_prev=None, depth_imbalance=0):
    vals=[x['close'] for x in candles]; spot=vals[-1]; strike=price(m.get('floor_strike'))
    if not strike or len(vals)<26:raise ValueError('Missing official strike or insufficient Coinbase candles')
    if time.time()-candles[-1]['t']>190:raise ValueError('Stale Coinbase prices')
    now=time.time();left=ts(m.get('close_time'))-now
    ret=lambda n:(spot/vals[-1-n]-1) if vals[-1-n] else 0
    r1,r3,r5,r10=ret(1),ret(3),ret(5),ret(10)
    diffs=[math.log(vals[i]/vals[i-1]) for i in range(1,len(vals))]
    vol=max(.00012,pstdev(diffs[-25:]))
    # Simple remaining-window uncertainty, NOT an independently calibrated probability.
    rem=max(1,left)/60
    z=(spot-strike)/(max(spot,1)*vol*math.sqrt(rem))
    base_prob=sigmoid(z*1.5)
    ema=lambda n:sum(vals[-n+i]*(2/(n+1))*(1-2/(n+1))**(n-1-i) for i in range(n))/sum((2/(n+1))*(1-2/(n+1))**i for i in range(n))
    fast, slow=ema(8),ema(21)
    avgv=sum(x['vol'] for x in candles[-21:-1])/20
    volume_ratio=candles[-1]['vol']/max(avgv,1e-9)
    candle=candles[-1]
    body=(candle['close']-candle['open'])/max(candle['high']-candle['low'],.01)
    signals=[]
    def sig(name, value, detail, available=True): signals.append({'name':name,'score':round(max(-1,min(1,value)),3) if available else None,'detail':detail,'available':available})
    sig('1 · Strike distance',math.tanh(z/1.8),f'z={z:.2f}')
    sig('2 · 3m momentum',math.tanh(r3/(vol*3.5)),f'{r3*100:.3f}%')
    sig('3 · 10m momentum',math.tanh(r10/(vol*5.)),f'{r10*100:.3f}%')
    sig('4 · Momentum acceleration',math.tanh((r1-r5/5)/(vol*1.6)), '1m vs 5m pace')
    sig('5 · EMA trend',math.tanh((fast-slow)/(spot*vol*2.)),f'EMA8 {fast:.2f} / EMA21 {slow:.2f}')
    sig('6 · Candle strength',body,'Last 1m candle body')
    sig('7 · Volume-confirmed move',math.tanh(r3/(vol*2))*min(1.0,volume_ratio/2),f'Volume {volume_ratio:.2f}×')
    sig('8 · Kalshi bid depth',depth_imbalance,'YES versus NO visible bids')
    if futures_now:
        sig('9 · Futures basis',math.tanh((futures_now['mark']/futures_now['index']-1)/.0008), 'Mark/index basis')
    else:sig('9 · Futures basis',0,'Futures feed unavailable',False)
    if futures_now and futures_prev and futures_prev.get('oi'):
        change=futures_now['oi']/futures_prev['oi']-1
        sig('10 · OI pressure',math.tanh(change/.003)*math.tanh(r3/(vol*3)),f'OI change {change*100:.2f}%')
    else:sig('10 · OI pressure',0,'Need two futures samples',False)
    available=[s for s in signals if s['available']]
    mean=sum(s['score'] for s in available)/len(available)
    # Blend strike model & short-horizon direction features. Heuristic, uncalibrated.
    probability=max(.03,min(.97,.70*base_prob+.30*sigmoid(mean*2.2)))
    votes=sum(1 for s in available if s['score']>0.13) if probability>=.5 else sum(1 for s in available if s['score']<-.13)
    confidence=max(probability,1-probability)
    return dict(probability=probability,confidence=confidence,votes=votes,signals=signals,spot=spot,strike=strike,left=left,vol=vol,volume_ratio=volume_ratio, futures_ready=bool(futures_now),available=len(available))

def read_config():
    f='settings.json'
    try: return {**DEFAULT,**json.load(open(f))}
    except (FileNotFoundError,json.JSONDecodeError):return DEFAULT.copy()

def fetch_state(old_fut=None):
    m=market()
    if not m:raise ValueError('No currently open KXBTC15M contract returned by Kalshi')
    candles=spot_candles(); y,n=book(m['ticker'])
    if not y or not n:raise ValueError('Incomplete Kalshi order book')
    # YES ask is derived from best NO bid, and vice versa.
    yb=y[0][0];nb=n[0][0];ya=1-nb;na=1-yb
    if ya<=yb or na<=nb: raise ValueError('Crossed or invalid orderbook')
    ydepth=sum(v for p,v in y[:5]);ndepth=sum(v for p,v in n[:5]);imb=(ydepth-ndepth)/max(1,ydepth+ndepth)
    fut=futures() if read_config()['futures_enabled'] else None
    outcome=compute(candles,m,yb,ya,nb,na,fut,old_fut,imb)
    outcome.update(ticker=m['ticker'],yes_bid=yb,yes_ask=ya,no_bid=nb,no_ask=na,close_time=m['close_time'], futures=fut)
    return outcome

def signal_trade(c,s):
    side='YES' if s['probability']>.5 else 'NO'; model=s['probability'] if side=='YES' else 1-s['probability']
    ask=s['yes_ask'] if side=='YES' else s['no_ask'];bid=s['yes_bid'] if side=='YES' else s['no_bid']
    edge=model-ask
    reason=[]
    if not c['min_seconds']<=s['left']<=c['max_seconds']:reason.append('Outside entry window')
    if s['confidence']<c['minimum_confidence']:reason.append('Low confidence')
    if s['votes']<c['minimum_votes']:reason.append('Signal votes below minimum')
    if not c['min_price']<=ask<=c['max_price']:reason.append('Price outside range')
    if ask-bid>c['max_spread']:reason.append('Spread too wide')
    if edge<c['minimum_edge']:reason.append('Insufficient estimated edge')
    return {'side':side,'ask':ask,'bid':bid,'edge':edge,'votes':s['votes'],'reasons':reason,'eligible':not reason}

def total_today(conn):
    midnight=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    row=conn.execute('SELECT COALESCE(SUM(pnl),0) pnl, COUNT(*) n FROM trades WHERE entry_ts>=?',(midnight,)).fetchone()
    return float(row['pnl']),int(row['n'])

def settlement(ticker):
    return get(KALSHI+'/markets/'+ticker).get('market',{})

def process(c,s):
    conn=db();now=time.time(); notes=[]
    open_trades=conn.execute("SELECT * FROM trades WHERE status='OPEN'").fetchall()
    for r in open_trades:
        if r['ticker']==s['ticker']:
            bid=s['yes_bid'] if r['side']=='YES' else s['no_bid']
            left=s['left']
        else:
            bid=None;left=-1
        exit_type=None;out=None;f=0
        if bid is not None and (bid-r['entry'])*100>=c['tp_cents']:exit_type='Take profit'
        if bid is not None and (bid-r['entry'])*100<=-c['sl_cents']:exit_type='Stop loss'
        if bid is not None and left<=12:exit_type='Before close'
        if bid is not None and now-r['entry_ts']>=c['max_hold_seconds']:exit_type='Max hold'
        if exit_type:
            out=max(.001,bid-c['slippage_cents']/100);f=fee(out,r['quantity'])
        elif left<0:
            try:
                resolved=settlement(r['ticker']);result=str(resolved.get('result','')).lower()
                if result not in ('yes','no'):
                    notes.append('Awaiting settlement: '+r['ticker']);continue
                out=1.0 if result.upper()==r['side'] else 0.0;exit_type='Official settlement';f=0
            except Exception as e:
                notes.append('Settlement check failed: '+str(e)[:100]);continue
        if exit_type:
            pnl=round(r['quantity']*(out-r['entry'])-r['entry_fee']-f,2)
            conn.execute("UPDATE trades SET exit=?,exit_fee=?,exit_ts=?,pnl=?,status='CLOSED',reason=? WHERE id=?",(out,f,now,pnl,exit_type,r['id']))
            notes.append(f"CLOSED {r['side']} {r['ticker']} | {exit_type} | ${pnl:+.2f}")
    conn.commit()
    open_trades=conn.execute("SELECT * FROM trades WHERE status='OPEN'").fetchall()
    pnl, count=total_today(conn)
    proposal=signal_trade(c,s)
    skip=list(proposal['reasons'])
    if any(r['ticker']==s['ticker'] for r in open_trades):skip.append('Already traded this market')
    if len(open_trades):skip.append('Open position exists')
    if count>=c['max_trades_day']:skip.append('Daily trade cap')
    if pnl<=-c['max_daily_loss']:skip.append('Daily loss limit')
    last=conn.execute('SELECT MAX(entry_ts) last FROM trades').fetchone()['last']
    if last and now-last<c['signal_cooldown']:skip.append('Cooldown')
    risk=sum(r['entry']*r['quantity'] for r in open_trades)
    if risk>=c['max_exposure']:skip.append('Exposure limit')
    if not skip:
        entry=min(.999,proposal['ask']+c['slippage_cents']/100)
        n=min(int(c['stake_usd']/max(entry,.01)),int((c['max_exposure']-risk)/max(entry,.01)))
        n=min(n,int((c['bankroll']+pnl-risk)/max(entry,.01)))
        if n<1:skip.append('Capital insufficient')
        else:
            f=fee(entry,n)
            if proposal['edge'] <= c['minimum_edge']+c['slippage_cents']/100+f/n:skip.append('Edge below fee/slippage buffer')
            else:
                conn.execute('INSERT INTO trades(ticker,side,quantity,entry,entry_fee,entry_ts,status,reason,signal_json) VALUES(?,?,?,?,?,?,?,?,?)',(s['ticker'],proposal['side'],n,entry,f,now,'OPEN','Paper entry',json.dumps(s)))
                conn.commit();notes.append(f"OPENED {n} {proposal['side']} @ {entry:.3f} | estimated edge {proposal['edge']:.3f}")
    conn.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?)',(now,s['ticker'],s['spot'],s['strike'],s['yes_bid'],s['yes_ask'],s['no_bid'],s['no_ask'],s['probability'],s['confidence'],json.dumps(s['signals'])))
    conn.execute('DELETE FROM snapshots WHERE ts<?',(now-86400*7,));conn.commit();conn.close()
    return {'notes':notes,'skips':skip,'proposal':proposal,'daily_pnl':pnl,'daily_count':count}
