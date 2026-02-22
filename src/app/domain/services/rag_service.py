import os
import faiss
import pickle
import markdown
import logging
from typing import List, Dict, Any
from pathlib import Path
from pypdf import PdfReader
from google import genai
from google.genai import types

from app.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)

class PortfolioRAG:
    """Implementação nativa de RAG sem Langchain/Grafo pesado."""
    
    def __init__(self, data_dir: str = "certificados-wesley/portfolio-content"):
        self.data_dir = Path(data_dir)
        self.index_path = "vector_store.faiss"
        self.metadata_path = "vector_metadata.pkl"
        
        # O novo Google GenAI SDK
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.embedding_model = "gemini-embedding-001"
        
        self.index = None
        self.chunks_metadata = []
        
    def initialize_or_build(self):
        """Carrega RAG do disco ou reconstrói se index não existir ou estiver desatualizado.
        
        Reconstrói automaticamente se qualquer markdown for mais recente que o index salvo.
        Isso garante que novos documentos em projects/ sejam sempre indexados.
        """
        index_exists = os.path.exists(self.index_path) and os.path.exists(self.metadata_path)
        needs_rebuild = not index_exists

        if index_exists:
            index_mtime = os.path.getmtime(self.index_path)
            md_files = list(self.data_dir.glob("**/*.md"))
            newest_md = max((f.stat().st_mtime for f in md_files), default=0)
            if newest_md > index_mtime:
                logger.info("Markdowns mais recentes que o índice detectados. Recriando RAG...")
                needs_rebuild = True

        if needs_rebuild:
            logger.info("Gerando Embeddings de todos os markdowns (incluindo projects/)...")
            self._build_index()
        else:
            logger.info("RAG Index atualizado encontrado. Carregando...")
            self.index = faiss.read_index(self.index_path)
            with open(self.metadata_path, "rb") as f:
                self.chunks_metadata = pickle.load(f)

    def _build_index(self):
        """Lê markdowns do seu portfólio e constrói a Vector Store nativa"""
        if not self.data_dir.exists():
            logger.warning(f"Diretório do seu portfólio não encontrado: {self.data_dir}")
            return
            
        all_text = ""
        # Lê recursivamente todos os markdowns: raiz + projects/ + trabalhos/ etc.
        md_files = sorted(self.data_dir.glob("**/*.md"))
        logger.info(f"RAG: indexando {len(md_files)} arquivos markdown...")
        for md_file in md_files:
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    # Usa o caminho relativo como label para facilitar debug
                    rel = md_file.relative_to(self.data_dir)
                    all_text += f"\n\n--- Documento: {rel} ---\n{content}"
            except Exception as e:
                logger.error(f"Erro lendo RAG file {md_file}: {str(e)}")
                
        # Splitter muito simples (nativo, zero Langchain memory)
        chunks = self._chunk_text(all_text, chunk_size=1000, overlap=100)
        
        # Gerar Embeddings pelo Gemini
        embeddings = []
        for i, chunk in enumerate(chunks):
            response = self.client.models.embed_content(
                model=self.embedding_model,
                contents=chunk,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
            )
            embeddings.append(response.embeddings[0].values)
            self.chunks_metadata.append({"id": i, "text": chunk})
            
        if not embeddings:
            logger.warning("Nenhum texto extraído. RAG Vazio.")
            return
            
        import numpy as np
        emb_matrix = np.array(embeddings).astype('float32')
        dimension = emb_matrix.shape[1]
        
        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(emb_matrix)
        
        # Salva disco
        faiss.write_index(self.index, self.index_path)
        with open(self.metadata_path, 'wb') as f:
            pickle.dump(self.chunks_metadata, f)
            
        logger.info(f"RAG Index Base gerado com sucesso! ({len(chunks)} chunks).")

    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        words = text.split()
        chunks = []
        i = 0
        while i < len(words):
            chunk = " ".join(words[i:i + chunk_size])
            chunks.append(chunk)
            i += chunk_size - overlap
        return chunks
        
    def retrieve(self, query: str, top_k: int = 3) -> str:
        """Busca vetor similar na Base FAISS"""
        if not self.index or self.index.ntotal == 0:
            return ""
            
        response = self.client.models.embed_content(
            model=self.embedding_model,
            contents=query,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
        )
        query_embedding = response.embeddings[0].values
        
        import numpy as np
        query_matrix = np.array([query_embedding]).astype('float32')
        
        # Busca
        distances, indices = self.index.search(query_matrix, top_k)
        
        context_parts = []
        for idx in indices[0]:
            if idx != -1 and idx < len(self.chunks_metadata):
                context_parts.append(self.chunks_metadata[idx]['text'])
                
        return "\n...\n".join(context_parts)
