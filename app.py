import os
qs = Transaction.query.filter_by(wallet_id=wallet_id).order_by(Transaction.id.asc())
rows = ["id;wallet_id;amount;tx_type;created_at"]
for t in qs:
rows.append(f"{t.id};{t.wallet_id};{t.amount};{t.tx_type};{t.created_at.isoformat()}")
csv_data = "\n".join(rows)
return Response(csv_data, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=wallet_{wallet_id}.csv"})


# Simple dashboard (public demo, NOT sensitive data)
@app.route("/dashboard", methods=["GET"])
def dashboard():
page = """
<html><head><meta charset='utf-8'><title>nono-wallet</title>
<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto;max-width:900px;margin:40px auto;padding:0 16px;color:#111}
h1{margin-bottom:4px} .card{border:1px solid #ddd;border-radius:14px;padding:16px;margin:12px 0;box-shadow:0 2px 6px rgba(0,0,0,.04)}
input,button{padding:8px 10px;border-radius:10px;border:1px solid #ccc}button{cursor:pointer}
table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #eee;padding:8px;text-align:left}
</style></head><body>
<h1>nono-wallet</h1>
<div class='card'>
<h3>Create Wallet</h3>
<input id='name' placeholder='name (optional)'>
<input id='init' type='number' step='0.01' placeholder='initial_balance=0'>
<button onclick='createW()'>Create</button>
<pre id='out1'></pre>
</div>


<div class='card'>
<h3>Balance / Tx</h3>
<input id='wid' type='number' placeholder='wallet_id'>
<button onclick='balance()'>Get Balance</button>
<button onclick='txs()'>List Tx</button>
<button onclick='csv()'>Export CSV</button>
<pre id='out2'></pre>
</div>


<div class='card'>
<h3>Deposit / Withdraw</h3>
<input id='amt' type='number' step='0.01' placeholder='amount'>
<button onclick='dep()'>Deposit</button>
<button onclick='wd()'>Withdraw</button>
<pre id='out3'></pre>
</div>


<script>
const API = '';
const token = localStorage.getItem('API_TOKEN') || '';
function idem(){ return Math.random().toString(36).slice(2)+Date.now(); }
async function post(p, body, out){
const r = await fetch(API+p,{method:'POST', headers:{'Content-Type':'application/json','X-Api-Token':token,'Idempotency-Key':idem()}, body:JSON.stringify(body)});
document.getElementById(out).textContent = await r.text();
}
async function get(p, out){
const r = await fetch(API+p);
document.getElementById(out).textContent = await r.text();
}
async function createW(){ await post('/wallet/create', {name:document.getElementById('name').value, initial_balance:document.getElementById('init').value}, 'out1'); }
async function balance(){ const id=document.getElementById('wid').value; await get('/wallet/balance?wallet_id='+id,'out2'); }
async function txs(){ const id=document.getElementById('wid').value; await get('/transactions?wallet_id='+id,'out2'); }
async function csv(){ const id=document.getElementById('wid').value; window.location='/export/csv?wallet_id='+id; }
async function dep(){ const id=document.getElementById('wid').value; const a=document.getElementById('amt').value; await post('/wallet/deposit',{wallet_id:parseInt(id), amount:a}, 'out3'); }
async function wd(){ const id=document.getElementById('wid').value; const a=document.getElementById('amt').value; await post('/wallet/withdraw',{wallet_id:parseInt(id), amount:a}, 'out3'); }
</script>
</body></html>
"""
return Response(page, mimetype="text/html")


# ---------------------------
# Bootstrap
# ---------------------------
if __name__ == "__main__":
logging.basicConfig(level=logging.INFO)
with app.app_context():
db.create_all()
app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
from flask import render_template

@app.route("/")
def dashboard():
    return render_template("dashboard.html", api_token=os.getenv("API_TOKEN",""))
