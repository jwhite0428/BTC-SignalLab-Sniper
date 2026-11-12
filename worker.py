import time, json, traceback, os
from engine import fetch_state,process,read_config

def main():
    previous=None
    print('BTC SignalLab PAPER worker starting. No trading credentials required.',flush=True)
    while True:
        config=read_config()
        try:
            state=fetch_state(previous)
            if state.get('futures'):previous=state['futures']
            result=process(config,state)
            with open('worker_status.json','w') as f:json.dump({'time':time.time(),'state':state,'result':result,'error':None},f)
            print(time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime()),state['ticker'],result['notes'] or result['skips'],flush=True)
        except Exception as e:
            msg=f'{type(e).__name__}: {e}'
            print(msg,flush=True)
            with open('worker_status.json','w') as f:json.dump({'time':time.time(),'error':msg},f)
        time.sleep(max(8,int(config['poll_seconds'])))
if __name__=='__main__':main()
