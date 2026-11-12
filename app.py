import streamlit as st
import json,time,os,pandas as pd
from engine import db,read_config,DEFAULT,signal_trade,fetch_state
st.set_page_config(page_title='BTC SignalLab', page_icon='🎯',layout='wide')
st.markdown('''<style>
.stApp {background:#0b1220;color:#f2f5fc} [data-testid="stMetric"] {background:#192538;border-radius:13px;padding:13px;border:1px solid #2e405c}
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] {color:#f5f7fc!important}
[data-testid="stSidebar"]{background:#151e30} h1,h2,h3,p,span,div,label {overflow-wrap:break-word}
.block-container{padding-top:1.2rem;max-width:1200px} button {min-height:42px}
@media(max-width:650px){.block-container{padding-left:1rem;padding-right:1rem}.stMetric{font-size:15px}}
</style>''',unsafe_allow_html=True)
st.title('🎯 BTC SignalLab · Sniper-style')
st.caption('Kalshi BTC 15-minute · 10-signal research engine · PAPER ONLY · no verified profitability')
settings=read_config()
with st.sidebar:
    st.header('Risk & Signal Settings')
    st.info('Changes affect the separate worker after its next poll. No live orders are sent.')
    keys=[('stake_usd','Stake USD',1.,100.,1.),('minimum_edge','Minimum estimated edge',.01,.25,.005),('minimum_votes','Minimum agreeing signals',2,10,1),('minimum_confidence','Minimum model confidence',.50,.95,.01),('min_seconds','Earliest close buffer (sec)',15,600,5),('max_seconds','Latest entry time remaining (sec)',120,850,10),('tp_cents','Take profit (¢)',2,50,1),('sl_cents','Stop loss (¢)',2,50,1),('max_daily_loss','Daily loss limit USD',5.,250.,5.),('max_trades_day','Daily max trades',1,100,1)]
    with st.form('settings'):
        changes={}
        for key,label,a,b,step in keys:
            v=settings[key]
            changes[key]=st.number_input(label,min_value=a,max_value=b,value=max(a,min(b,v)),step=step,key=key)
        changes['futures_enabled']=st.checkbox('Try Binance futures signals',value=settings['futures_enabled'])
        if st.form_submit_button('Save Settings',use_container_width=True):
            settings.update(changes)
            with open('settings.json','w') as f:json.dump(settings,f,indent=2)
            st.success('Saved. Worker will load changes on next cycle.')
try:
    status=json.load(open('worker_status.json'))
except Exception:status={}
if not status:
    st.warning('Worker has not generated data yet. Run `python worker.py` separately. If your hosting stops background processes, run the worker on an always-on machine.')
elif status.get('error'):
    st.error('Worker data error: '+status['error']+' · Verify Kalshi/Coinbase API connectivity and startup logs.')
    st.caption('Last worker check: '+time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime(status['time'])))
else:
    s=status['state'];r=status['result'];staleness=time.time()-status['time']
    if staleness>90:st.error(f'STALE feed: last update {int(staleness)} seconds ago. Do not rely on displayed odds.')
    c1,c2,c3,c4=st.columns(4)
    c1.metric('BTC spot',f"${s['spot']:,.2f}")
    c2.metric('Official strike',f"${s['strike']:,.2f}")
    c3.metric('Time remaining',f"{max(0,int(s['left']))}s")
    c4.metric('Model P(YES)',f"{s['probability']*100:.1f}%")
    st.subheader('Live Kalshi prices')
    c1,c2,c3,c4=st.columns(4)
    c1.metric('YES bid',f"{s['yes_bid']*100:.1f}¢");c2.metric('YES ask',f"{s['yes_ask']*100:.1f}¢")
    c3.metric('NO bid',f"{s['no_bid']*100:.1f}¢");c4.metric('NO ask',f"{s['no_ask']*100:.1f}¢")
    st.caption(f"Market: {s['ticker']} · Futures data: {'available' if s.get('futures_ready') else 'unavailable'} · {s['available']}/10 measured signals")
    p=r['proposal']
    st.subheader('Entry decision')
    a,b,c=st.columns(3)
    a.metric('Direction',p['side']);b.metric('Estimated edge',f"{p['edge']*100:.1f}pp");c.metric('Agreeing signals',str(p['votes']))
    if r['notes']:st.success(' | '.join(r['notes']))
    elif r['skips']:st.warning('NO ENTRY · '+' · '.join(r['skips']))
    else:st.success('Eligible signal')
    st.subheader('10 signal breakdown')
    records=[{'Signal':x['name'],'Score (-1 to +1)':x['score'],'Observation':x['detail'],'Feed':'LIVE' if x['available'] else 'MISSING'} for x in s['signals']]
    st.dataframe(pd.DataFrame(records),use_container_width=True,hide_index=True)
    st.caption('Scores and probabilities are heuristic estimates, not proven calibrated probabilities. Missing futures signals are shown explicitly.')
conn=db()
trades=pd.read_sql_query('SELECT * FROM trades ORDER BY id DESC LIMIT 250',conn)
closed=trades[trades['status']=='CLOSED'] if len(trades) else pd.DataFrame()
open_count=int((trades['status']=='OPEN').sum()) if len(trades) else 0
pnl=round(float(closed['pnl'].sum()),2) if len(closed) else 0
st.divider();st.subheader('Paper portfolio')
x,y,z=st.columns(3)
x.metric('Realized paper P&L',f'${pnl:+,.2f}')
y.metric('Closed trades',len(closed));z.metric('Open positions',open_count)
if len(closed):
    closed=closed.sort_values('exit_ts');closed['Equity P&L']=closed['pnl'].cumsum();st.line_chart(closed.set_index('exit_ts')['Equity P&L'])
if len(trades):
    st.dataframe(trades[['ticker','side','quantity','entry','entry_fee','exit','exit_fee','pnl','status','reason']].fillna(''),use_container_width=True,hide_index=True)
    st.download_button('Export trade history CSV',trades.to_csv(index=False),'btc_signal_lab_trades.csv','text/csv')
else:st.info('No paper trades yet. Strategy may skip windows while waiting for measured edge.')
conn.close()
st.caption('Data: public Kalshi & Coinbase APIs; optional Binance futures. Refresh the page for updated state. Background worker must be running separately. No real-money connectivity.')
