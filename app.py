DASHBOARD_HTML = """
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Nono Wallet Dashboard</title>
<style>
  :root{--bg:#0b0f14;--card:#111827;--line:#1f2833;--field:#0b1220;--text:#e6edf3;--muted:#9aa9b7}
  *{box-sizing:border-box}
  body{background:var(--bg);color:var(--text);font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0}
  header{padding:24px 32px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
  h1{font-size:22px;margin:0}
  main{padding:32px;max-width:1500px;margin:0 auto}
  .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:18px}
  .stat{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px}
  .stat .v{font-size:28px;font-weight:700}
  .card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px;margin-bottom:18px}
  .row{display:flex;gap:14px;flex-wrap:wrap}
  .row > *{flex:1;min-width:240px}
  label{display:block;margin:6px 0 8px}
  input,select,button{background:var(--field);color:var(--text);border:1px solid #243241;border-radius:12px;padding:12px 14px}
  input,select{width:100%}
  button{cursor:pointer}
  .btn-primary{background:#0b5cff}
  .btn-ghost{background:transparent}
  .muted{color:var(--muted)}
  table{width:100%;border-collapse:collapse;margin-top:14px;font-size:14px}
  th,td{border-bottom:1px solid #243241;padding:10px;text-align:right}
  .actions{display:flex;gap:10px;flex-wrap:wrap}
  .help{font-size:12px;opacity:.8}
  @media (max-width:1200px){ .grid{grid-template-columns:1fr 1fr} }
  @media (max-width:800px){ .grid{grid-template-columns:1fr} .row>*{min-width:100%} }
</style>
</head>
<body>
<header>
  <h1>نونو-والِت • لوحة التحكم</h1>
  <div class="muted help">الهيدر لكل الطلبات: <code>X-Api-Key</code> (يحفظ محليًا عندك)</div>
</header>

<main>

  <!-- أرقام مختصرة -->
  <section class="grid">
    <div class="stat"><div class="muted">إجمالي الإيداعات</div><div id="statDeposits" class="v">0.00</div></div>
    <div class="stat"><div class="muted">إجمالي السحوبات</div><div id="statWithdraws" class="v">0.00</div></div>
    <div class="stat"><div class="muted">إجمالي التحويلات</div><div id="statTransfers" class="v">0.00</div></div>
  </section>

  <!-- إعدادات سريعة -->
  <section class="card">
    <div class="row">
      <div>
        <label>API Token (هيدر X-Api-Key)</label>
        <input id="apiKey" placeholder="ضع التوكن هنا" />
        <div class="actions" style="margin-top:8px">
          <button id="btnSaveKey" class="btn-primary">حفظ</button>
          <button id="btnCopyKey" class="btn-ghost">نسخ</button>
        </div>
        <div class="help muted">يُحفظ في المتصفح (localStorage) — لا يُرسل إلا مع الطلبات.</div>
      </div>
      <div>
        <label>Wallet ID (معرّف المحفظة)</label>
        <input id="walletId" placeholder="uuid" />
        <div class="actions" style="margin-top:8px">
          <button id="btnCopyWallet" class="btn-ghost">نسخ</button>
        </div>
      </div>
      <div>
        <label>عمليات سريعة</label>
        <div class="actions">
          <button id="btnCreate" class="btn-primary">إنشاء محفظة</button>
          <button id="btnBalance" class="btn-ghost">عرض الرصيد</button>
        </div>
        <div class="help muted" id="balanceHint"></div>
      </div>
    </div>
  </section>

  <!-- عمليات -->
  <section class="card">
    <h3 style="margin-top:0">عمليات على المحفظة</h3>
    <div class="row">
      <div>
        <label>نوع العملية</label>
        <select id="op">
          <option value="deposit">إيداع</option>
          <option value="withdraw">سحب</option>
          <option value="transfer">تحويل إلى محفظة أخرى</option>
        </select>
      </div>
      <div>
        <label>المبلغ</label>
        <input id="amount" type="number" step="0.00000001" value="200" />
      </div>
      <div id="toWalletWrap" style="display:none">
        <label>To Wallet ID</label>
        <input id="toWalletId" placeholder="uuid" />
      </div>
      <div style="align-self:end">
        <button id="btnDo" class="btn-primary">تنفيذ</button>
      </div>
    </div>
  </section>

  <!-- السجل + فلتر + CSV -->
  <section class="card">
    <div class="row">
      <div>
        <label>تصفية بالسجل</label>
        <input id="fltWallet" placeholder="wallet_id (اختياري)" />
      </div>
      <div>
        <label>النوع</label>
        <select id="fltType">
          <option value="">الكل</option>
          <option>create</option><option>deposit</option><option>withdraw</option>
          <option>transfer_in</option><option>transfer_out</option>
        </select>
      </div>
      <div>
        <label>من تاريخ</label>
        <input id="fltFrom" type="datetime-local" />
      </div>
      <div>
        <label>إلى تاريخ</label>
        <input id="fltTo" type="datetime-local" />
      </div>
      <div style="align-self:end" class="actions">
        <button id="btnLoad" class="btn-primary">تحميل السجل</button>
        <a id="lnkCsv" href="#" target="_blank">تصدير CSV</a>
      </div>
    </div>

    <table id="tbl">
      <thead><tr><th>الوقت</th><th>المعرف</th><th>Wallet</th><th>النوع</th><th>المبلغ</th></tr></thead>
      <tbody></tbody>
    </table>
  </section>

</main>

<script>
  // تخزين محلي للتوكن والوالت
  const LS_KEY = 'nono_api_key';
  const LS_WAL = 'nono_last_wallet';
  const $ = s => document.querySelector(s);

  const op = $('#op');
  op.addEventListener('change', ()=> $('#toWalletWrap').style.display = (op.value==='transfer')?'block':'none');

  // تهيئة الحقول
  const savedKey = localStorage.getItem(LS_KEY)||'';
  $('#apiKey').value = savedKey;
  const savedWal = localStorage.getItem(LS_WAL)||'';
  $('#walletId').value = savedWal;

  function hdr(){ return {"X-Api-Key": $('#apiKey').value.trim()}; }
  function fmt(x){ return new Intl.NumberFormat('en-US',{maximumFractionDigits:8}).format(x); }

  $('#btnSaveKey').onclick = ()=>{ localStorage.setItem(LS_KEY, $('#apiKey').value.trim()); alert('تم الحفظ'); };
  $('#btnCopyKey').onclick = async ()=>{ await navigator.clipboard.writeText($('#apiKey').value.trim()); alert('نُسخ التوكن'); };
  $('#btnCopyWallet').onclick = async ()=>{ await navigator.clipboard.writeText($('#walletId').value.trim()); alert('نُسخ Wallet ID'); };

  $('#btnCreate').onclick = async ()=>{
    const name = 'wallet-'+Date.now();
    const r = await fetch('/wallet/create',{method:'POST',headers:{...hdr(),"Content-Type":"application/json"},body:JSON.stringify({name})});
    const j = await r.json();
    if(!j.ok){ alert(j.error||'خطأ'); return; }
    $('#walletId').value = j.wallet.id;
    localStorage.setItem(LS_WAL, j.wallet.id);
    alert('تم إنشاء محفظة');
  };

  $('#btnBalance').onclick = async ()=>{
    const id = $('#walletId').value.trim();
    if(!id) return alert('Wallet ID?');
    const r = await fetch(`/wallet/balance?wallet_id=${encodeURIComponent(id)}`, {headers: hdr()});
    const j = await r.json();
    $('#balanceHint').textContent = j.ok ? ('الرصيد الحالي: '+fmt(j.wallet.balance)) : (j.error||'!');
  };

  $('#btnDo').onclick = async ()=>{
    const id = $('#walletId').value.trim();
    const amount = parseFloat($('#amount').value||'0');
    if(!id) return alert('Wallet ID?');
    if(!(amount>0)) return alert('المبلغ يجب أن يكون > 0');

    let url = '', body = {};
    if(op.value==='transfer'){
      const toId = $('#toWalletId').value.trim();
      if(!toId) return alert('To Wallet ID?');
      url = '/wallet/transfer'; body = {from_wallet_id:id, to_wallet_id:toId, amount};
    }else if(op.value==='deposit'){
      url = '/wallet/deposit'; body = {wallet_id:id, amount};
    }else{
      url = '/wallet/withdraw'; body = {wallet_id:id, amount};
    }
    const r = await fetch(url,{method:'POST',headers:{...hdr(),"Content-Type":"application/json"},body:JSON.stringify(body)});
    const j = await r.json();
    if(!j.ok){ alert(j.error||'خطأ'); return; }
    alert('تمت العملية');
  };

  $('#btnLoad').onclick = loadTx;
  async function loadTx(){
    const w = $('#fltWallet').value.trim();
    const t = $('#fltType').value;
    const f = $('#fltFrom').value ? new Date($('#fltFrom').value).toISOString() : '';
    const to = $('#fltTo').value ? new Date($('#fltTo').value).toISOString() : '';
    const qs = new URLSearchParams();
    if(w) qs.set('wallet_id', w);
    if(t) qs.set('type', t);
    if(f) qs.set('date_from', f);
    if(to) qs.set('date_to', to);

    const r = await fetch(`/transactions?${qs.toString()}`, {headers: hdr()});
    const j = await r.json();
    const tbody = $('#tbl tbody');
    tbody.innerHTML = '';
    let dep=0, wd=0, tr=0;

    if(j.ok){
      for(const it of j.items){
        if(it.type==='deposit') dep+=it.amount;
        if(it.type==='withdraw') wd+=it.amount;
        if(it.type==='transfer_in' || it.type==='transfer_out') tr+=it.amount;

        const trEl = document.createElement('tr');
        trEl.innerHTML = `<td>${new Date(it.created_at).toLocaleString()}</td>
          <td class="muted">${it.id}</td>
          <td class="muted">${it.wallet_id}</td>
          <td>${it.type}</td>
          <td>${fmt(it.amount)}</td>`;
        tbody.appendChild(trEl);
      }
    }
    // تحديث الإحصاءات
    $('#statDeposits').textContent = fmt(dep);
    $('#statWithdraws').textContent = fmt(wd);
    $('#statTransfers').textContent = fmt(tr);

    // CSV link
    const lnk = $('#lnkCsv');
    lnk.href = `/transactions/export.csv?${qs.toString()}`;
    lnk.onclick = (e)=>{ e.preventDefault(); window.open(lnk.href + (qs.toString()?'&':'?') + 'dl=1', '_blank'); }
  }
</script>
</body>
</html>
"""
