<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8" />
  <title>Area Sviluppatore – Damiano</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    :root { --primary:#2563eb; --bg:#f6f7fb; --card:#fff; --muted:#6b7280; }
    body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; background:var(--bg); }
    .wrap { max-width: 1000px; margin: 40px auto; padding: 0 16px; }
    .card { background:var(--card); border-radius:16px; box-shadow: 0 8px 30px rgba(0,0,0,.06); padding:20px; }
    h1 { margin:0 0 16px; font-size: 24px; }
    h2 { margin:20px 0 10px; font-size: 18px; }
    .row { display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin: 12px 0 18px; }
    label { font-size:14px; color:var(--muted); }
    input[type="text"], input[type="password"], input[type="url"] {
      padding:10px 12px; border:1px solid #e5e7eb; border-radius:10px; min-width: 260px;
    }
    button {
      padding:10px 14px; border:0; border-radius:10px; background:var(--primary); color:#fff; cursor:pointer;
    }
    button.ghost { background:#e5e7eb; color:#111827; }
    table { width:100%; border-collapse:collapse; margin-top:10px; }
    th, td { padding:10px 8px; border-bottom:1px solid #eee; text-align:left; font-size:14px; }
    th { color:#111827; }
    td small { color:var(--muted); }
    .right { text-align:right; }
    .badge { font-size:12px; padding:2px 8px; border-radius:999px; background:#eef2ff; color:#3730a3; }
    #status { margin-top:10px; font-size:14px; }
    .ok { color:#15803d; } .err{ color:#b91c1c; }

    .storage-box { border:1px dashed #e5e7eb; border-radius:12px; padding:12px; background:#fafbff; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>⚙️ Area Sviluppatore</h1>

      <!-- Connessione backend -->
      <div class="row">
        <div>
          <label>Backend URL</label><br />
          <input id="baseUrl" type="url" placeholder="https://damiano-backend-xxx.onrender.com" />
        </div>
        <div>
          <label>X-Secret</label><br />
          <input id="xSecret" type="password" placeholder="admin secret" />
        </div>
        <div>
          <br />
          <button id="saveBtn">Salva</button>
          <button class="ghost" id="refreshBtn">Aggiorna contatti</button>
        </div>
      </div>

      <div id="status"></div>

      <!-- Pannello STORAGE -->
      <h2>📁 Percorso di salvataggio</h2>
      <div class="storage-box">
        <div class="row" style="margin:0 0 8px">
          <button id="btnReadStorage" class="ghost">📁 Leggi percorso</button>
          <button id="btnSetStorage">✏️ Imposta percorso…</button>
        </div>
        <div id="storageInfo">
          <div><small class="mono">data_dir: <span id="curDir">—</span></small></div>
          <div style="margin-top:6px">
            <small class="mono">files: <span id="curFiles">—</span></small>
          </div>
        </div>
        <div style="margin-top:8px;color:#6b7280;font-size:13px">
          Suggerimenti: su Render usare percorsi <em>del server</em>, es. <span class="mono">/tmp/damiano-data</span> (non persistente) oppure un
          disco montato, es. <span class="mono">/var/damiano-data</span> (persistente).
        </div>
      </div>

      <!-- Tabella contatti -->
      <h2>Contatti</h2>
      <table id="tbl">
        <thead>
          <tr>
            <th>Nome</th>
            <th>Email</th>
            <th>Prossima ricorrenza</th>
            <th class="right">Azione</th>
          </tr>
        </thead>
        <tbody id="tbody">
          <tr><td colspan="4"><small>Caricamento contatti…</small></td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    const el = (id) => document.getElementById(id);
    const LS_BASE = "dev_base_url";
    const LS_SECRET = "dev_x_secret";

    // Defaults
    el("baseUrl").value = localStorage.getItem(LS_BASE) || "https://damiano-backend-ancz.onrender.com";
    el("xSecret").value = localStorage.getItem(LS_SECRET) || "";

    const getBase = () => el("baseUrl").value.trim().replace(/\/+$/,'');
    const getSecret = () => el("xSecret").value;

    el("saveBtn").addEventListener("click", () => {
      localStorage.setItem(LS_BASE, getBase());
      localStorage.setItem(LS_SECRET, getSecret());
      setStatus("Impostazioni salvate ✔️", true);
      loadRecords();
      readStorage();
    });

    el("refreshBtn").addEventListener("click", () => loadRecords());
    el("btnReadStorage").addEventListener("click", () => readStorage());
    el("btnSetStorage").addEventListener("click", () => setStorage());

    function setStatus(msg, ok=false){
      el("status").className = ok ? "ok" : "err";
      el("status").textContent = msg;
    }

    // ===== STORAGE =====
    async function readStorage(){
      const base = getBase();
      if(!base){ setStatus("Imposta il Backend URL", false); return; }
      try{
        const res = await fetch(`${base}/admin/storage`, {
          headers: { "X-Secret": getSecret() }
        });
        if(!res.ok){
          const err = await res.json().catch(()=>({detail: res.statusText}));
          setStatus("Errore lettura storage: " + (err.detail||res.status), false);
          return;
        }
        const data = await res.json();
        renderStorage(data);
        setStatus("Percorso letto correttamente", true);
      }catch(e){
        setStatus("Errore rete (lettura storage)", false);
      }
    }

    function renderStorage(obj){
      el("curDir").textContent = obj?.data_dir || "—";
      const files = Array.isArray(obj?.files) ? obj.files : [];
      el("curFiles").textContent = files.length ? files.join(", ") : "—";
    }

    async function setStorage(){
      const base = getBase();
      if(!base){ setStatus("Imposta il Backend URL", false); return; }
      const secret = getSecret();
      if(!secret){ setStatus("Inserisci X-Secret", false); return; }

      const path = prompt("Inserisci NUOVO percorso sul server (es. /tmp/damiano-data o /var/damiano-data):");
      if(path === null) return; // annullato
      const body = { path: String(path||"").trim() };
      if(!body.path){ setStatus("Percorso non valido", false); return; }

      try{
        const res = await fetch(`${base}/admin/storage`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            "X-Secret": secret
          },
          body: JSON.stringify(body)
        });
        const data = await res.json();
        if(res.ok && data.ok){
          renderStorage(data);
          setStatus(`Percorso impostato: ${data.data_dir}`, true);
        }else{
          setStatus("Errore impostazione: " + (data.detail || JSON.stringify(data)), false);
        }
      }catch(e){
        setStatus("Errore rete (impostazione storage)", false);
      }
    }

    // ===== RECORDS =====
    async function loadRecords(){
      const base = getBase();
      if(!base){ setStatus("Imposta il Backend URL", false); return; }
      el("tbody").innerHTML = `<tr><td colspan="4"><small>Caricamento contatti…</small></td></tr>`;
      try{
        const res = await fetch(`${base}/records`);
        const data = await res.json();
        renderTable(data || []);
        setStatus(`Caricati ${ (data||[]).length } contatti`, true);
      }catch(e){
        el("tbody").innerHTML = `<tr><td colspan="4"><small>Errore caricamento contatti</small></td></tr>`;
        setStatus("Errore di rete nel recupero dei contatti", false);
      }
    }

    function renderTable(records){
      const tbody = el("tbody");
      if(!records.length){
        tbody.innerHTML = `<tr><td colspan="4"><small>Nessun contatto presente</small></td></tr>`;
        return;
      }
      tbody.innerHTML = "";
      for(const r of records){
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><strong>${r.nome||""} ${r.cognome||""}</strong><br><small class="badge">${r.id}</small></td>
          <td>${r.email||"<small class='err'>—</small>"}</td>
          <td>${r.prossima_ricorrenza || "<small>—</small>"}</td>
          <td class="right">
            <button onclick="sendNow('${r.id}',0)">Invia ora</button>
            <button class="ghost" onclick="sendNow('${r.id}',1)" title="Invia e avanza di 1 anno">Invia +1y</button>
          </td>
        `;
        tbody.appendChild(tr);
      }
    }

    async function sendNow(rid, advance){
      const base = getBase();
      const secret = getSecret();
      if(!secret){ setStatus("Inserisci X-Secret", false); return; }

      if(!confirm("Vuoi inviare subito l'email per questo contatto?")) return;

      try{
        const res = await fetch(`${base}/admin/send-now/${rid}?advance=${advance}`, {
          method: "POST",
          headers: { "X-Secret": secret }
        });
        const data = await res.json();
        if(res.ok && data.ok){
          setStatus("✅ Email inviata correttamente", true);
        }else{
          setStatus("❌ Errore: " + (data.detail || JSON.stringify(data)), false);
        }
      }catch(e){
        setStatus("❌ Errore di rete nell'invio", false);
      }
    }

    // Auto-load all'avvio
    loadRecords();
    readStorage();
  </script>
</body>
</html>






