import base64
import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class DocumentEntry:
    path: Path
    filename: str
    title_pt: str
    title_en: str
    category: str  # resume_pt | resume_en | certificate


class DocumentCatalogService:
    def __init__(self, base_dir: str = "certificados-wesley"):
        self.base_dir = Path(base_dir)
        self.overrides_path = self.base_dir / "portfolio-translate" / "overrides.json"
        self._entries: list[DocumentEntry] = []
        self._overrides: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        self._overrides = self._load_overrides()
        self._entries = self._discover_entries()

    def _load_overrides(self) -> dict[str, str]:
        if not self.overrides_path.exists():
            return {}
        data = json.loads(self.overrides_path.read_text(encoding="utf-8"))
        certs = data.get("certs", {})
        result: dict[str, str] = {}
        for filename, meta in certs.items():
            if isinstance(meta, dict) and meta.get("title"):
                result[filename] = meta["title"]
        return result

    def _discover_entries(self) -> list[DocumentEntry]:
        entries: list[DocumentEntry] = []
        for path in sorted(self.base_dir.glob("*.pdf")):
            filename = path.name
            title_pt = self._clean_filename(filename)
            title_en = self._overrides.get(filename, title_pt)
            category = self._classify(filename)
            entries.append(
                DocumentEntry(
                    path=path,
                    filename=filename,
                    title_pt=title_pt,
                    title_en=title_en,
                    category=category,
                )
            )
        return entries

    def _classify(self, filename: str) -> str:
        normalized = self._normalize(filename)
        if "resume" in normalized:
            return "resume_en"
        if "curriculo" in normalized:
            return "resume_pt"
        return "certificate"

    def _clean_filename(self, filename: str) -> str:
        stem = Path(filename).stem
        return " ".join(stem.replace("_", " ").split())

    def _normalize(self, text: str) -> str:
        text = unicodedata.normalize("NFKD", text.lower())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return " ".join(text.replace(".pdf", "").replace("-", " ").replace("_", " ").split())

    def get_resume(self, language: str = "pt") -> Optional[DocumentEntry]:
        preferred = "resume_en" if language == "en" else "resume_pt"
        for entry in self._entries:
            if entry.category == preferred:
                return entry
        return None

    def list_certificates(self, language: str = "pt") -> list[str]:
        certs = [e for e in self._entries if e.category == "certificate"]
        if language == "en":
            return [e.title_en for e in certs]
        return [e.title_pt for e in certs]

    def get_certificate_count(self) -> int:
        return len([e for e in self._entries if e.category == "certificate"])

    def find_best_document(self, query: str, language: str = "pt") -> Optional[DocumentEntry]:
        normalized_query = self._normalize(query)
        if not normalized_query:
            return None

        indexed_certificate = self._find_certificate_by_index(normalized_query)
        if indexed_certificate is not None:
            return indexed_certificate

        if any(term in normalized_query for term in ("curriculo", "curriculum", "cv", "resume")):
            resume = self.get_resume(language)
            if resume:
                return resume

        best_entry: Optional[DocumentEntry] = None
        best_score = 0.0

        for entry in self._entries:
            candidates = {
                self._normalize(entry.filename),
                self._normalize(entry.title_pt),
                self._normalize(entry.title_en),
            }
            for candidate in candidates:
                if not candidate:
                    continue
                if candidate in normalized_query or normalized_query in candidate:
                    score = 1.0
                else:
                    score = SequenceMatcher(None, normalized_query, candidate).ratio()
                if score > best_score:
                    best_score = score
                    best_entry = entry

        if best_score >= 0.58:
            return best_entry
        return None

    def build_certificate_list_message(self, language: str = "pt") -> str:
        certificates = self.list_certificates(language)
        if not certificates:
            return (
                "No momento eu não encontrei certificados cadastrados para envio."
                if language == "pt"
                else "I couldn't find any certificates available to send right now."
            )

        header = (
            f"Eu tenho {len(certificates)} certificados em PDF. Você pode pedir qualquer um desta lista:"
            if language == "pt"
            else f"I have {len(certificates)} PDF certificates. You can ask me for any of these:"
        )
        linhas = [header, ""]
        for idx, title in enumerate(certificates, start=1):
            linhas.append(f"{idx}. {title}")
        return "\n".join(linhas)

    def load_base64(self, entry: DocumentEntry) -> str:
        return base64.b64encode(entry.path.read_bytes()).decode("utf-8")

    def build_delivery_filename(self, entry: DocumentEntry, language: str = "pt") -> str:
        base_title = entry.title_en if language == "en" and entry.category == "certificate" else entry.title_pt
        normalized = unicodedata.normalize("NFKD", base_title)
        ascii_name = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        ascii_name = re.sub(r"[^A-Za-z0-9._ -]+", "", ascii_name).strip().replace(" ", "_")
        if not ascii_name.lower().endswith(".pdf"):
            ascii_name += ".pdf"
        return ascii_name or entry.filename

    def _find_certificate_by_index(self, normalized_query: str) -> Optional[DocumentEntry]:
        certs = [e for e in self._entries if e.category == "certificate"]
        match = re.search(r"\b(?:certificado|certificate)?\s*(\d{1,2})\b", normalized_query)
        if not match:
            return None
        index = int(match.group(1))
        if 1 <= index <= len(certs):
            return certs[index - 1]
        return None
