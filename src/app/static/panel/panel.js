/* ------------------- State ------------------- */
let currentPage = 1;
let conversaJid = null;
let showHidden = false;  // toggle "exibir ocultos"

/* ------------------- Boot ------------------- */
document.addEventListener('DOMContentLoaded', () => {
  navigateTo('dashboard');
  loadDashboard();
});

/* ------------------- Navigation ------------------- */
function closeSidebar() {
  document.getElementById('layout').classList.remove('sidebar-open');
  document.body.classList.remove('sidebar-open');
}

function toggleSidebar() {
  const layout = document.getElementById('layout');
  layout.classList.toggle('sidebar-open');
  document.body.classList.toggle('sidebar-open', layout.classList.contains('sidebar-open'));
}

function navigateTo(page) {
  closeSidebar();
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const el = document.getElementById('page-' + page);
  if (el) el.classList.add('active');
  const nav = document.querySelector(`[data-page="${page}"]`);
  if (nav) nav.classList.add('active');

  switch (page) {
    case 'dashboard': loadDashboard(); break;
    case 'conversas': loadConversas(1); break;
    case 'instancias': loadInstancias(); break;
    case 'allowlist': loadAllowlist(); break;
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
let conversasSearchTerm = '';

async function loadConversas(page = 1) {
  currentPage = page;
  const listEl = document.getElementById('conversas-list');
  const paginEl = document.getElementById('conversas-pagination');
  listEl.innerHTML = '<tr><td colspan="5" class="loading">Carregando...</td></tr>';

  const instancia = getInstanciaConversas();
  if (!instancia) {
    toast('Selecione uma instância primeiro', 'red');
    return;
  }

  const params = new URLSearchParams({
    instancia,
    page: String(page),
    per_page: '10',
    show_hidden: String(showHidden),
  });
  if (conversasSearchTerm.trim()) {
    params.set('search', conversasSearchTerm.trim());
  }
  const data = await api('GET', `/api/panel/conversations?${params.toString()}`);
  if (!data) return;

  if (!data.conversas.length) {
    listEl.innerHTML = '<tr><td colspan="5" class="empty">Nenhuma conversa encontrada.</td></tr>';
    return;
  }

  listEl.innerHTML = data.conversas.map(c => {
    const dt = c.ultima_mensagem_dt ? new Date(c.ultima_mensagem_dt + 'Z').toLocaleString('pt-BR') : '—';
    const preview = (c.ultima_mensagem || '').substring(0, 55) + (c.ultima_mensagem && c.ultima_mensagem.length > 55 ? '...' : '');
    const jidEnc = c.whatsapp_id.replace(/@/g, '__at__');
    const ocultaLabel = c.oculta ? '👁 Exibir' : '📦 Arquivar';
    const ocultaTitle = c.oculta ? 'Restaurar conversa' : 'Arquivar (ocultar da lista)';
    const rowClass = c.oculta ? 'conversa-row conversa-oculta' : 'conversa-row';
    return `
      <tr class="${rowClass}">
        <td data-label="Contato">
          <strong>${escHtml(c.nome)}</strong>
          ${c.oculta ? '<span class="badge-arquivado">Arquivado</span>' : ''}
          <br><small style="color:var(--text-muted)">${c.numero}</small>
        </td>
        <td data-label="Última mensagem" class="conversa-preview">
          ${escHtml(preview) || '—'}
        </td>
        <td data-label="Horário" class="conversa-dt">${dt}</td>
        <td data-label="IA">
          <label class="toggle">
            <input type="checkbox" ${c.ia_ativa ? 'checked' : ''} onchange="toggleIA(getInstanciaConversas(), '${c.numero}', this.checked)">
            <span class="toggle-slider"></span>
          </label>
        </td>
        <td data-label="Ações" class="acoes-cell">
          <button onclick="verHistorico('${jidEnc}', '${escHtml(c.nome)}')"
                  class="btn-histórico" title="Ver histórico">💬</button>
          <button onclick="toggleArquivar('${c.id}', ${c.oculta})"
                  class="btn-arquivar ${c.oculta ? 'btn-restaurar' : ''}"
                  title="${ocultaTitle}">${ocultaLabel}</button>
          <button onclick="excluirConversa('${c.id}', '${escHtml(c.nome)}')"
                  class="btn-excluir" title="Excluir conversa e histórico">🗑</button>
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
  // Prioriza o seletor de instância da tela de Filtros, se existir,
  // senão usa o seletor de Conversas.
  const selFiltros = document.getElementById('inst-select-filtros');
  if (selFiltros && selFiltros.value) {
    return selFiltros.value;
  }

  const selConversas = document.getElementById('inst-select');
  return (selConversas && selConversas.value) ? selConversas.value : '';
}

function getInstanciaConversas() {
  const selConversas = document.getElementById('inst-select');
  return (selConversas && selConversas.value) ? selConversas.value : '';
}

async function toggleIA(instancia, chatJid, ativo) {
  if (!instancia) { toast('Selecione uma instância primeiro', 'red'); return; }
  const ok = await api('POST', '/api/panel/ia/toggle', { instancia, chat_jid: chatJid, ia_ativa: ativo });
  if (ok) toast(ativo ? '✅ IA ativada' : '🔴 IA desativada');
  else toast('Erro ao alterar IA', 'red');
}

/* ------------------- Toggle show hidden ------------------- */
function toggleShowHidden() {
  showHidden = !showHidden;
  const btn = document.getElementById('btn-show-hidden');
  if (btn) {
    btn.classList.toggle('ativo', showHidden);
    btn.title = showHidden ? 'Ocultar arquivados' : 'Exibir arquivados';
    btn.textContent = showHidden ? '👁 Ocultar arquivados' : '👁 Exibir arquivados';
  }
  loadConversas(1);
}

/* ------------------- Arquivar / Excluir ------------------- */
async function toggleArquivar(clienteId, ocultoAtual) {
  const novoEstado = !ocultoAtual;
  const ok = await api('PATCH', `/api/panel/conversations/${clienteId}/ocultar`, { oculta: novoEstado });
  if (ok) {
    toast(novoEstado ? '📦 Conversa arquivada' : '✅ Conversa restaurada');
    loadConversas(currentPage);
  } else {
    toast('Erro ao arquivar conversa', 'red');
  }
}

async function excluirConversa(clienteId, nome) {
  const confirmado = confirm(`Excluir conversa de "${nome}" permanentemente?\n\nTodo o histórico de mensagens será apagado e não poderá ser recuperado.`);
  if (!confirmado) return;
  const ok = await api('DELETE', `/api/panel/conversations/${clienteId}`);
  if (ok) {
    toast('🗑 Conversa excluída');
    loadConversas(currentPage);
  } else {
    toast('Erro ao excluir conversa', 'red');
  }
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
    const dt = m.data_hora ? new Date(m.data_hora + 'Z').toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '';
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

  // Limpa o prefixo se já veio da API para não duplicar
  const cleanBase64 = base64Qr.startsWith('data:image/') ? base64Qr : 'data:image/png;base64,' + base64Qr;
  document.getElementById('qr-img').src = cleanBase64;

  overlay.style.display = 'flex';
}

function fecharModalQR() {
  document.getElementById('qr-modal').style.display = 'none';
  loadInstancias();
}

/* ------------------- Allowlist / Blocklist ------------------- */
async function loadAllowlist() {
  const instancia = getInstancia();
  if (!instancia) {
    toast('Selecione uma instância primeiro', 'red');
    return;
  }
  const data = await api('GET', `/api/panel/allowlist?instancia=${encodeURIComponent(instancia)}`);
  if (!data) return;
  document.getElementById('allowlist-input').value = data.allowlist || '';
  document.getElementById('blocklist-input').value = data.blocklist || '';
}

async function saveAllowlist() {
  const instancia = getInstancia();
  if (!instancia) {
    toast('Selecione uma instância primeiro', 'red');
    return;
  }
  const allowlist = document.getElementById('allowlist-input').value.trim();
  const blocklist = document.getElementById('blocklist-input').value.trim();
  const ok = await api('POST', '/api/panel/allowlist', { instancia, allowlist, blocklist });
  if (ok) toast('✅ Allowlist/blocklist atualizada para a instância selecionada!');
  else toast('Erro ao salvar', 'red');
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
