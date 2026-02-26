/* ------------------- State ------------------- */
let currentPage = 1;
let conversaJid = null;

/* ------------------- Boot ------------------- */
document.addEventListener('DOMContentLoaded', () => {
  navigateTo('dashboard');
  loadDashboard();
});

/* ------------------- Navigation ------------------- */
function navigateTo(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const el = document.getElementById('page-' + page);
  if (el) el.classList.add('active');
  const nav = document.querySelector(`[data-page="${page}"]`);
  if (nav) nav.classList.add('active');

  switch (page) {
    case 'dashboard':    loadDashboard();    break;
    case 'conversas':    loadConversas(1);   break;
    case 'instancias':   loadInstancias();   break;
    case 'allowlist':    loadAllowlist();    break;
  }
}

/* ------------------- API helper ------------------- */
async function api(method, path, body = null) {
  const opts = {
    method,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (r.status === 401) { window.location.href = '/panel/login'; return null; }
  return r.ok ? r.json() : null;
}

/* ------------------- Toast ------------------- */
function toast(msg, type = 'green') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast ${type} show`;
  setTimeout(() => t.classList.remove('show'), 3000);
}

/* ------------------- Dashboard ------------------- */
async function loadDashboard() {
  const data = await api('GET', '/api/panel/dashboard');
  if (!data) return;

  document.getElementById('stat-conversas').textContent = data.total_conversas;
  document.getElementById('stat-mensagens').textContent = data.total_mensagens;
  document.getElementById('stat-hoje').textContent = data.mensagens_hoje;

  const iaStatus = document.getElementById('ia-status-global');
  iaStatus.innerHTML = '';
  data.instancias.forEach(inst => {
    const ativo = data.ia_status_global[inst] !== false;
    iaStatus.innerHTML += `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border)">
        <span style="font-size:.875rem">${inst}</span>
        <label class="toggle" title="${ativo ? 'IA Ativa' : 'IA Inativa'}">
          <input type="checkbox" ${ativo ? 'checked' : ''} onchange="toggleIA('${inst}', null, this.checked)">
          <span class="toggle-slider"></span>
        </label>
      </div>`;
  });
}

/* ------------------- Conversas ------------------- */
async function loadConversas(page = 1) {
  currentPage = page;
  const listEl = document.getElementById('conversas-list');
  const paginEl = document.getElementById('conversas-pagination');
  listEl.innerHTML = '<tr><td colspan="5" class="loading">Carregando...</td></tr>';

  const data = await api('GET', `/api/panel/conversations?page=${page}&per_page=20`);
  if (!data) return;

  if (!data.conversas.length) {
    listEl.innerHTML = '<tr><td colspan="5" class="empty">Nenhuma conversa ainda.</td></tr>';
    return;
  }

  listEl.innerHTML = data.conversas.map(c => {
    const dt = c.ultima_mensagem_dt ? new Date(c.ultima_mensagem_dt + 'Z').toLocaleString('pt-BR') : '—';
    const badgeClass = c.ia_ativa ? 'green' : 'red';
    const preview = (c.ultima_mensagem || '').substring(0, 55) + (c.ultima_mensagem && c.ultima_mensagem.length > 55 ? '...' : '');
    const jidEnc = c.whatsapp_id.replace(/@/g, '__at__');
    return `
      <tr>
        <td>
          <strong>${escHtml(c.nome)}</strong><br>
          <small style="color:var(--text-muted)">${c.numero}</small>
        </td>
        <td style="max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-muted);font-size:.82rem">
          ${escHtml(preview) || '—'}
        </td>
        <td style="white-space:nowrap;font-size:.8rem;color:var(--text-muted)">${dt}</td>
        <td>
          <label class="toggle">
            <input type="checkbox" ${c.ia_ativa ? 'checked' : ''} onchange="toggleIA(getInstancia(), '${c.numero}', this.checked)">
            <span class="toggle-slider"></span>
          </label>
        </td>
        <td>
          <button onclick="verHistorico('${jidEnc}', '${escHtml(c.nome)}')" 
                  style="background:none;border:1px solid var(--border);color:var(--text-dim);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:.78rem">
            Histórico
          </button>
        </td>
      </tr>`;
  }).join('');

  // Paginação
  paginEl.innerHTML = '';
  if (data.pages > 1) {
    for (let i = 1; i <= data.pages; i++) {
      paginEl.innerHTML += `<button class="${i === page ? 'active' : ''}" onclick="loadConversas(${i})">${i}</button>`;
    }
  }
}

function getInstancia() {
  // Lê a primeira instância do dashboard (simplificado)
  // Para múltiplas instâncias, poderia ter um seletor
  return document.getElementById('inst-select')?.value || '';
}

async function toggleIA(instancia, chatJid, ativo) {
  if (!instancia) { toast('Selecione uma instância primeiro', 'red'); return; }
  const ok = await api('POST', '/api/panel/ia/toggle', { instancia, chat_jid: chatJid, ia_ativa: ativo });
  if (ok) toast(ativo ? '✅ IA ativada' : '🔴 IA desativada');
  else    toast('Erro ao alterar IA', 'red');
}

/* ------------------- Histórico ------------------- */
async function verHistorico(jidEnc, nome) {
  conversaJid = jidEnc;
  const listEl = document.getElementById('conversas-list');
  const chatEl = document.getElementById('chat-wrap');
  const chatTitle = document.getElementById('chat-nome');
  const chatMsgs = document.getElementById('chat-messages');

  chatTitle.textContent = nome;
  chatMsgs.innerHTML = '<div class="loading">Carregando histórico...</div>';
  chatEl.style.display = 'flex';

  const data = await api('GET', `/api/panel/conversations/${jidEnc}/history?limite=80`);
  if (!data || !data.mensagens.length) {
    chatMsgs.innerHTML = '<div class="empty">Nenhuma mensagem encontrada.</div>';
    return;
  }

  chatMsgs.innerHTML = data.mensagens.map(m => {
    const dt = m.data_hora ? new Date(m.data_hora + 'Z').toLocaleTimeString('pt-BR', {hour:'2-digit', minute:'2-digit'}) : '';
    return `
      <div class="chat-msg ${m.direcao === 'RECEBIDA' ? 'recebida' : 'enviada'}">
        <div>${escHtml(m.texto || '')}</div>
        <div class="msg-time">${dt}</div>
      </div>`;
  }).join('');
  chatMsgs.scrollTop = chatMsgs.scrollHeight;
}

function fecharHistorico() {
  document.getElementById('chat-wrap').style.display = 'none';
  conversaJid = null;
}

/* ------------------- Instâncias ------------------- */
async function loadInstancias() {
  const grid = document.getElementById('instances-grid');
  grid.innerHTML = '<div class="loading">Verificando instâncias...</div>';

  const data = await api('GET', '/api/panel/instances');
  if (!data) return;

  grid.innerHTML = data.map(inst => {
    const isOpen = inst.status === 'open';
    const badgeClass = isOpen ? 'green' : inst.status.startsWith('erro') ? 'red' : 'yellow';
    const badgeLabel = isOpen ? '🟢 Conectado' : inst.status === 'close' ? '🔴 Desconectado' : inst.status;
    return `
      <div class="instance-card">
        <h3>${inst.nome}</h3>
        <div class="status"><span class="badge ${badgeClass}">${badgeLabel}</span></div>
        <button class="btn-connect" onclick="conectarInstancia('${inst.nome}')">
          ${isOpen ? '🔄 Reconectar' : '🔌 Conectar (QR Code)'}
        </button>
      </div>`;
  }).join('');
}

async function conectarInstancia(nome) {
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '⏳ Gerando QR...';

  const data = await api('POST', `/api/panel/instances/${nome}/connect`);
  btn.disabled = false;
  btn.textContent = '🔌 Conectar (QR Code)';

  if (!data) { toast('Erro ao gerar QR Code', 'red'); return; }

  if (data.base64) {
    abrirModalQR(data.base64, nome);
  } else if (data.status === 'already_connected') {
    toast('✅ Instância já está conectada!');
    loadInstancias();
  } else {
    toast('Resposta inesperada da API', 'red');
  }
}

function abrirModalQR(base64Qr, nome) {
  const overlay = document.getElementById('qr-modal');
  document.getElementById('qr-instance-name').textContent = nome;
  document.getElementById('qr-img').src = 'data:image/png;base64,' + base64Qr;
  overlay.style.display = 'flex';
}

function fecharModalQR() {
  document.getElementById('qr-modal').style.display = 'none';
  loadInstancias();
}

/* ------------------- Allowlist / Blocklist ------------------- */
async function loadAllowlist() {
  const data = await api('GET', '/api/panel/allowlist');
  if (!data) return;
  document.getElementById('allowlist-input').value = data.allowlist || '';
  document.getElementById('blocklist-input').value = data.blocklist || '';
}

async function saveAllowlist() {
  const allowlist = document.getElementById('allowlist-input').value.trim();
  const blocklist = document.getElementById('blocklist-input').value.trim();
  const ok = await api('POST', '/api/panel/allowlist', { allowlist, blocklist });
  if (ok) toast('✅ Allowlist/blocklist atualizada!');
  else    toast('Erro ao salvar', 'red');
}

/* ------------------- Logout ------------------- */
async function logout() {
  await api('POST', '/api/panel/logout');
  window.location.href = '/panel/login';
}

/* ------------------- Utils ------------------- */
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
