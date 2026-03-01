import gc
import os
import re
import faiss
import pickle
import logging
import numpy as np
from difflib import SequenceMatcher
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from google import genai
from google.genai import types

from app.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração de qualidade de retrieval
# ---------------------------------------------------------------------------
# Distância L2 máxima aceita. Chunks acima deste valor são descartados.
# Valores menores = mais restritivo. Calibrado para gemini-embedding-001 (768d).
MAX_L2_DISTANCE = 1.2

# Arquivos considerados contexto base — carregados como fallback garantido
# quando nenhum chunk relevante é encontrado via FAISS.
FALLBACK_FILES = {"CURRICULO.md", "STACKS.md"}


class ProjectDetector:
    """
    Descobre projetos dinamicamente a partir dos nomes de arquivo em projects/.
    Técnica portada de ProjetoKeywordDetector.java.

    Para cada arquivo encontrado em `projects/`, gera automaticamente keywords
    a partir do nome do arquivo (hífens, underscores, partes individuais).
    Permite detectar quando o usuário menciona um projeto pelo nome / apelido.
    """

    def __init__(self, projects_dir: Path):
        self.projects_dir = projects_dir
        # {nome_normalizado: {"keywords": [...], "path": Path}}
        self._cache: Dict[str, Dict] = {}
        self._loaded = False

    def load(self):
        """Carrega/atualiza o catálogo de projetos do diretório."""
        if not self.projects_dir.exists():
            return
        self._cache.clear()
        for md_file in self.projects_dir.glob("*.md"):
            # Ignora variantes em inglês (sufixo -english)
            if md_file.stem.endswith("-english"):
                continue
            nome = md_file.stem.lower()
            keywords = self._gerar_keywords(nome)
            self._cache[nome] = {"keywords": keywords, "path": md_file}
        self._loaded = True
        logger.info(f"ProjectDetector: {len(self._cache)} projetos indexados")

    def _gerar_keywords(self, nome: str) -> List[str]:
        """
        Gera keywords automaticamente do nome do arquivo.
        Ex: "lol-matchmaking-fazenda" ->
            ["lol-matchmaking-fazenda", "lol matchmaking fazenda",
             "lolmatchmakingfazenda", "lol", "matchmaking", "fazenda"]
        """
        kws = [nome]
        kws.append(nome.replace("-", " ").replace("_", " "))
        kws.append(re.sub(r"[-_]", "", nome))
        partes = re.split(r"[-_]+", nome)
        for parte in partes:
            if len(parte) > 2 and parte not in kws:
                kws.append(parte)
        return kws

    def _fuzzy_match(self, kw: str, query_words: List[str]) -> bool:
        """
        Levenshtein aproximado via SequenceMatcher (stdlib, zero dependências).
        Portado de ContextSearchService.temSimilaridade() + calcularLevenshtein() (Java).
        Ratio >= 0.82 equivale a ~2 erros em palavra de 11 chars.
        Só aplica em keywords com 4+ chars para evitar falsos positivos.
        """
        if len(kw) < 4:
            return False
        for word in query_words:
            if len(word) < 3:
                continue
            ratio = SequenceMatcher(None, kw, word).ratio()
            if ratio >= 0.82:
                return True
        return False

    def detect(self, query: str) -> Optional[str]:
        """
        Retorna o conteúdo do markdown do projeto mencionado na query, ou None.
        1º tenta substring exato; se não achar, tenta fuzzy (SequenceMatcher).
        """
        if not self._loaded:
            self.load()
        query_lower = query.lower()
        query_words = query_lower.split()
        for nome, info in self._cache.items():
            matched = False
            match_type = ""
            for kw in info["keywords"]:
                if kw in query_lower:
                    matched = True
                    match_type = "exato"
                    break
                if self._fuzzy_match(kw, query_words):
                    matched = True
                    match_type = "fuzzy"
                    break
            if matched:
                try:
                    content = info["path"].read_text(encoding="utf-8")
                    logger.info(f"ProjectDetector: projeto '{nome}' detectado ({match_type}) → injetando markdown")
                    return f"--- Projeto: {nome} ---\n{content}"
                except Exception as e:
                    logger.error(f"ProjectDetector: erro lendo {info['path']}: {e}")
                    return None
        return None


class PortfolioRAG:
    """
    RAG com FAISS + Gemini Embeddings.

    Melhorias em relação à versão original:
    - 1.1 Source-aware chunking: metadata guarda source_file, is_project, is_fallback
    - 1.2 Score threshold L2: chunks irrelevantes são descartados
    - 1.3 Fallback garantido: curriculo + stacks injetados quando RAG retorna vazio
    - 1.4 Top-k dinâmico: retrieve_smart() detecta intenção e ajusta top_k
    - 1.5 On-demand project loading: ProjectDetector detecta projeto → injeta md completo
    """

    def __init__(self, data_dir: str = "certificados-wesley/portfolio-content"):
        self.data_dir = Path(data_dir)
        self.index_path = "vector_store.faiss"
        self.metadata_path = "vector_metadata.pkl"

        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.embedding_model = "gemini-embedding-001"

        self.index = None
        self.chunks_metadata: List[Dict] = []

        # Contexto de fallback (curriculo + stacks) — carregado na inicialização
        self._fallback_context: str = ""

        # Detector de projetos on-demand
        self.project_detector = ProjectDetector(self.data_dir / "projects")

    # -----------------------------------------------------------------------
    # Inicialização
    # -----------------------------------------------------------------------

    def initialize_or_build(self):
        """
        Carrega RAG do disco ou reconstrói se desatualizado.
        Também carrega: fallback_context e ProjectDetector.
        """
        index_exists = (
            os.path.exists(self.index_path) and os.path.exists(self.metadata_path)
        )
        needs_rebuild = not index_exists

        if index_exists:
            index_mtime = os.path.getmtime(self.index_path)
            md_files = list(self.data_dir.glob("**/*.md"))
            newest_md = max((f.stat().st_mtime for f in md_files), default=0)
            if newest_md > index_mtime:
                logger.info("Markdowns mais recentes que o índice. Recriando RAG...")
                needs_rebuild = True

        if needs_rebuild:
            logger.info("Gerando embeddings de todos os markdowns (incluindo projects/)...")
            self._build_index()
        else:
            logger.info("RAG Index atualizado encontrado. Carregando...")
            self.index = faiss.read_index(self.index_path)
            with open(self.metadata_path, "rb") as f:
                self.chunks_metadata = pickle.load(f)

        self._load_fallback_context()
        self.project_detector.load()

    def _load_fallback_context(self):
        """Carrega curriculo.md e stacks.md como contexto de fallback garantido."""
        parts = []
        for fname in FALLBACK_FILES:
            # Procura case-insensitive
            matches = list(self.data_dir.glob(f"**/{fname}"))
            if not matches:
                # Tenta sem case
                matches = [
                    f for f in self.data_dir.glob("**/*.md")
                    if f.name.upper() == fname.upper()
                ]
            if matches:
                try:
                    content = matches[0].read_text(encoding="utf-8")
                    parts.append(f"--- {fname} ---\n{content}")
                    logger.info(f"Fallback carregado: {matches[0]}")
                except Exception as e:
                    logger.error(f"Erro lendo fallback {fname}: {e}")
        self._fallback_context = "\n\n".join(parts)
        if self._fallback_context:
            logger.info("Contexto de fallback (curriculo+stacks) pronto.")
        else:
            logger.warning("Nenhum arquivo de fallback encontrado (CURRICULO.md / STACKS.md).")

    # -----------------------------------------------------------------------
    # Build
    # -----------------------------------------------------------------------

    def _build_index(self):
        """
        Reconstrói o índice FAISS com metadata source-aware por chunk.

        Estratégia de memória: processa em duas passagens para evitar manter
        all_chunks + embeddings + chunks_metadata simultaneamente na RAM.
          1ª passagem: monta all_chunks (texto + meta) e libera logo após geração dos embeddings.
          2ª passagem: cria emb_matrix e libera a lista de embeddings antes de adicionar ao FAISS.
        """
        if not self.data_dir.exists():
            logger.warning(f"Diretório do portfólio não encontrado: {self.data_dir}")
            return

        md_files = sorted(self.data_dir.glob("**/*.md"))
        logger.info(f"RAG: indexando {len(md_files)} arquivos markdown...")

        # --- 1ª passagem: extração de chunks -----------------------------------
        all_chunks: List[Tuple[str, Dict]] = []

        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8")
                rel = md_file.relative_to(self.data_dir)
                rel_str = str(rel).replace("\\", "/")

                is_project = "projects/" in rel_str
                is_fallback = md_file.name.upper() in {f.upper() for f in FALLBACK_FILES}

                tags = []
                frontmatter_match = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
                if frontmatter_match:
                    fm_text = frontmatter_match.group(1)
                    tags_match = re.search(r"tags:\s*\[(.*?)\]", fm_text)
                    if tags_match:
                        tags = [t.strip() for t in tags_match.group(1).split(",")]

                header = f"--- Documento: {rel_str} ---\n"
                if tags:
                    header += f"Tags: {', '.join(tags)}\n"

                texto_com_header = header + content
                # Libera o conteúdo bruto do arquivo da RAM imediatamente
                del content

                file_chunks = self._chunk_text(texto_com_header, chunk_size=1000, overlap=100)
                for chunk in file_chunks:
                    meta = {
                        "text": chunk,
                        "source": rel_str,
                        "is_project": is_project,
                        "is_fallback": is_fallback,
                    }
                    all_chunks.append((chunk, meta))
            except Exception as e:
                logger.error(f"Erro lendo {md_file}: {e}")

        if not all_chunks:
            logger.warning("Nenhum texto extraído. RAG vazio.")
            return

        total_chunks = len(all_chunks)

        # --- 2ª passagem: geração de embeddings (streaming, sem duplicar textos) --
        # Usa array numpy pré-alocado para evitar realocações sucessivas da lista Python
        embeddings_list: List[List[float]] = []
        self.chunks_metadata = []

        for i, (chunk_text, meta) in enumerate(all_chunks):
            response = self.client.models.embed_content(
                model=self.embedding_model,
                contents=chunk_text,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
            embeddings_list.append(response.embeddings[0].values)
            meta["id"] = i
            self.chunks_metadata.append(meta)

        # Libera all_chunks antes de criar a matriz numpy (pico de memória reduzido)
        del all_chunks
        gc.collect()

        emb_matrix = np.array(embeddings_list, dtype="float32")
        # Libera a lista de embeddings Python agora que temos o array numpy
        del embeddings_list
        gc.collect()

        dimension = emb_matrix.shape[1]
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(emb_matrix)
        del emb_matrix
        gc.collect()

        faiss.write_index(self.index, self.index_path)
        with open(self.metadata_path, "wb") as f:
            pickle.dump(self.chunks_metadata, f)

        logger.info(f"RAG Index gerado com sucesso! ({total_chunks} chunks).")

    # -----------------------------------------------------------------------
    # Retrieval
    # -----------------------------------------------------------------------

    @staticmethod
    def _calcular_top_k(query: str) -> int:
        """
        Top-k dinâmico por intenção.
        Portado de PortfolioPromptService.calcularLimiteContextos() (Java).
        """
        lower = query.lower()
        if any(k in lower for k in ("quais projetos", "todos os projetos", "listar projetos", "list projects")):
            return 10
        if any(k in lower for k in ("trabalho", "emprego", "experiência", "experiencia", "carreira", "onde trabalh")):
            return 6
        if any(k in lower for k in ("stack", "tecnolog", "linguagem", "framework", "ferramenta")):
            return 5
        return 3  # default

    def retrieve(self, query: str, top_k: int = 3) -> str:
        """
        Busca FAISS com threshold de distância L2 e fallback garantido.
        Prefira `retrieve_smart()` que calcula top_k automaticamente.
        """
        if not self.index or self.index.ntotal == 0:
            logger.warning("RAG vazio, usando fallback.")
            return self._fallback_context

        response = self.client.models.embed_content(
            model=self.embedding_model,
            contents=query,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        query_vec = np.array([response.embeddings[0].values]).astype("float32")

        # Busca mais candidatos para filtrar por threshold
        k_busca = min(top_k * 3, self.index.ntotal)
        distances, indices = self.index.search(query_vec, k_busca)

        context_parts = []
        fontes_usadas = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1 or idx >= len(self.chunks_metadata):
                continue
            if dist > MAX_L2_DISTANCE:
                continue  # descarta por threshold
            if len(context_parts) >= top_k:
                break
            meta = self.chunks_metadata[idx]
            context_parts.append(meta["text"])
            fontes_usadas.append(meta.get("source", "?"))

        if context_parts:
            logger.info(f"RAG retrieval: {len(context_parts)} chunks (fontes: {fontes_usadas})")
            return "\n...\n".join(context_parts)

        # Nenhum chunk passou o threshold → fallback garantido
        logger.info("RAG: nenhum chunk relevante encontrado. Usando fallback (curriculo+stacks).")
        return self._fallback_context

    def retrieve_smart(self, query: str) -> str:
        """
        Retrieval com top_k dinâmico baseado na intenção da query.
        Use este método em vez de retrieve() para respostas mais precisas.
        """
        top_k = self._calcular_top_k(query)
        logger.info(f"RAG retrieve_smart: top_k={top_k} para query: '{query[:60]}'")
        return self.retrieve(query, top_k=top_k)

    def load_project_if_mentioned(self, query: str) -> Optional[str]:
        """
        Detecta se um projeto é mencionado na query e retorna seu markdown completo.
        Retorna None se nenhum projeto for detectado.
        Portado de ProjetoKeywordDetector + carregarMarkdownPorProjeto (Java).
        """
        return self.project_detector.detect(query)

    # -----------------------------------------------------------------------
    # Utilitários
    # -----------------------------------------------------------------------

    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        words = text.split()
        chunks = []
        i = 0
        while i < len(words):
            chunks.append(" ".join(words[i: i + chunk_size]))
            i += chunk_size - overlap
        return chunks
