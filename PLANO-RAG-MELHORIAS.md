# Plano de Melhorias RAG — Bot WhatsApp Wesley

Inspirado nas técnicas do projeto `wmakeouthill.github.io` (Java/Spring).
Mapeamento completo das técnicas existentes lá → implementação equivalente ou superior em Python/FAISS.

---

## Referência: Técnicas do projeto Java

| Classe Java | Técnica | Arquivo |
|---|---|---|
| `ContextSearchService` | Scoring léxico (stems + Levenshtein) + Score threshold (0.4) + Tag boost | `domain/service/ContextSearchService.java` |
| `ProjetoKeywordDetector` | Keywords 100% dinâmicas do nome de arquivo + tags do frontmatter | `domain/service/ProjetoKeywordDetector.java` |
| `PortfolioPromptService` | Top-k dinâmico por intenção + On-demand project loading | `domain/service/PortfolioPromptService.java` |
| `TokenBudgetService` | Redução automática de tokens: histórico → contextos → system prompt | `domain/service/TokenBudgetService.java` |

---

## Estado Atual do RAG Python

### `PortfolioRAG` (`rag_service.py`)

- ✅ FAISS IndexFlatL2 com Gemini Embeddings (`gemini-embedding-001`)
- ✅ Chunking simples por palavras (1000 words, 100 overlap)
- ✅ Indexação recursiva `**/*.md`
- ✅ Auto-rebuild por mtime
- ❌ `top_k` fixo em 3 — sem considerar intenção da pergunta
- ❌ Sem threshold de distância — retorna qualquer chunk mesmo irrelevante
- ❌ Sem fallback garantido — se query é vaga, não garante curriculo/stacks
- ❌ Sem source metadata por chunk — não sabe de qual arquivo veio
- ❌ Sem detecção de projeto por nome — não carrega markdown completo on-demand
- ❌ Sem tags semânticas por arquivo

### `AtendimentoService` (`bot_service.py`)

- ✅ Detecção de formato: áudio / planilha / texto
- ✅ RAG → Gemini → gTTS (agêntico)
- ✅ RAG → Gemini → openpyxl Excel (agêntico)
- ❌ `top_k` fixo em 3 — não varia por tipo de pergunta
- ❌ Sem injeção de projeto on-demand no contexto
- ❌ Sem fallback de contexto quando RAG retorna pouco

---

## Plano de Implementação

### Fase 1 — `rag_service.py`: Source metadata + Threshold + Fallback + Top-k dinâmico

#### 1.1 — Source-aware chunking `[ ]`

Guardar no metadata de cada chunk: `source_file`, `is_project`, `is_fallback`.

- Doc: Java faz isso via `PortfolioMarkdownResource(nome, caminho, conteudo, projeto, preferencialFallback, tags)`
- Python: adicionar ao dicionário `chunks_metadata[i]`:

  ```python
  {
    "id": i,
    "text": chunk,
    "source": "projects/lol-matchmaking-fazenda.md",
    "is_project": True,
    "is_fallback": False  # True para curriculo.md, stacks.md
  }
  ```

#### 1.2 — Score threshold em L2 `[ ]`

FAISS retorna distância L2. Distâncias altas = irrelevante.

- Java usa `MIN_SCORE = 0.4` no scoring léxico
- Python: definir `MAX_L2_DISTANCE = 1.2` (calibrado empiricamente)
  - Resultados com `distance > MAX_L2_DISTANCE` são descartados
  - Se 0 resultados sobrar → fallback automático

#### 1.3 — Fallback garantido (curriculo + stacks) `[ ]`

Quando `retrieve()` não acha nada relevante (todos acima do threshold):

- Java: chunks marcados `preferencialFallback=True` injetados automaticamente
- Python: arquivos `CURRICULO.md` e `STACKS.md` guardados como texto bruto no init,
  retornados como contexto base quando score baixo

#### 1.4 — Top-k dinâmico por intenção `[ ]`

Detectar intenção da query e ajustar `top_k`:

```python
# Inspirado em PortfolioPromptService.calcularLimiteContextos()
def _calcular_top_k(query: str) -> int:
    lower = query.lower()
    if any(k in lower for k in ("quais projetos", "todos os projetos", "list")):
        return 10
    if any(k in lower for k in ("trabalho", "emprego", "experiência", "carreira")):
        return 6
    if any(k in lower for k in ("stack", "tecnolog", "linguagem", "framework")):
        return 5
    return 3  # default
```

#### 1.5 — On-demand project loading `[ ]`

Detectar nome de projeto na query → carregar o markdown completo do arquivo (bypassa FAISS).

- Java: `ProjetoKeywordDetector.detectarProjetosRelevantes()` + `portfolioContentPort.carregarMarkdownPorProjeto()`
- Python:
  - `ProjectDetector`: lê nomes dos arquivos em `projects/` → gera keywords automáticas
  - Ex: `lol-matchmaking-fazenda.md` → keywords `["lol", "matchmaking", "fazenda", "lol matchmaking fazenda"]`
  - Fuzzy match (fuzz Levenshtein ou simples `in`) contra query
  - Se detectado: lê o arquivo `.md` completo e concatena no contexto

---

### Fase 2 — `bot_service.py`: Usar os novos recursos

#### 2.1 — Substituir `retrieve(q, top_k=3)` por `retrieve_smart(q)` `[ ]`

Chama `_calcular_top_k` internamente, retorna contexto otimizado.

#### 2.2 — Injetar projeto on-demand no contexto `[ ]`

Antes da chamada Gemini:

```python
projeto_md = self.rag.load_project_if_mentioned(texto)
if projeto_md:
    contexto = projeto_md + "\n---\n" + contexto
```

#### 2.3 — Fallback de contexto visível no log `[ ]`

Logar quando o fallback garantido for ativado para facilitar debug.

---

### Fase 3 — Token Budget (médio prazo) `[ ]`

Implementar `TokenBudgetService` equivalente:

- Estimar tokens: `len(texto) / 4` (aprox.)
- Limite: 30.000 tokens (Gemini 2.0 Flash suporta 1M, mas custo)
- Estratégia: reduzir `top_k` → truncar contexto → avisar no log

---

## Progresso

| Item | Status | Implementado em |
|---|---|---|
| 1.1 Source-aware chunking | ✅ concluído | `rag_service.py` → `_build_index()` — cada chunk tem `source`, `is_project`, `is_fallback` |
| 1.2 Score threshold L2 | ✅ concluído | `rag_service.py` → `retrieve()` — `MAX_L2_DISTANCE = 1.2`, chunks acima descartados |
| 1.3 Fallback garantido | ✅ concluído | `rag_service.py` → `_load_fallback_context()` — CURRICULO.md + STACKS.md injetados quando RAG retorna vazio |
| 1.4 Top-k dinâmico | ✅ concluído | `rag_service.py` → `_calcular_top_k()` + `retrieve_smart()` — projetos=10, trabalho=6, stack=5, default=3 |
| 1.5 On-demand project loading | ✅ concluído | `rag_service.py` → `ProjectDetector` — keywords automáticas do nome do arquivo, detect() retorna md completo |
| 2.1 retrieve_smart no bot_service | ✅ concluído | `bot_service.py` → `self.rag.retrieve_smart(texto)` em todos os pontos |
| 2.2 Projeto on-demand no contexto | ✅ concluído | `bot_service.py` → `projeto_md = self.rag.load_project_if_mentioned(texto)` antes de qualquer resposta |
| 2.3 Log de fallback | ✅ concluído | `rag_service.py` → `logger.info("RAG: nenhum chunk relevante...")` |
| 3.1 Token budget | ⬜ futuro | — |

---

## Notas de implementação

### `ProjectDetector` (`rag_service.py`)

Classe autônoma que carrega o catálogo de projetos de `projects/*.md` (excluindo `-english`).
Para cada arquivo, gera keywords:

- Nome completo: `lol-matchmaking-fazenda`
- Com espaços: `lol matchmaking fazenda`
- Sem separadores: `lolmatchmakingfazenda`
- Partes individuais: `lol`, `matchmaking`, `fazenda`

Detecção é por **substring na query** (simples, sem fuzzy — suficiente para o caso de uso).
Se detectado, retorna o conteúdo completo do `.md`, que é **injetado antes do contexto FAISS** no prompt.

### Fallback garantido

Arquivos em `FALLBACK_FILES = {"CURRICULO.md", "STACKS.md"}` são carregados em memória no `initialize_or_build()`.
Quando `retrieve()` não encontra nenhum chunk com `distance <= MAX_L2_DISTANCE`, retorna `_fallback_context` diretamente.
Log identifica quando o fallback foi ativado.

### Source-aware metadata

Cada chunk agora carrega:

```python
{
  "id": 42,
  "text": "...",
  "source": "projects/lol-matchmaking-fazenda.md",
  "is_project": True,
  "is_fallback": False
}
```

Facilita debug futuro (ex: token budget pode priorizar/remover por tipo).
