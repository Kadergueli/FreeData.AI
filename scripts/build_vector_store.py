
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.config import settings

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
MANIFEST_PATH = DOCS_DIR / "manifest.json"


def _raise_for_api_error(resp: requests.Response, step: str) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        detail = (getattr(resp, "text", "") or "").strip()
        if len(detail) > 400:
            detail = detail[:400] + "..."
        status = getattr(resp, "status_code", "?")
        raise RuntimeError(
            f"[FreeData.AI RAG] Échec {step} (HTTP {status}) : {detail or exc}"
        ) from exc


def _supabase_headers(prefer: str | None = None) -> dict:
    key = settings.write_key
    if not key or not settings.supabase_url:
        raise RuntimeError("SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY sont requis pour écrire dans rag_*.")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
    """Découpe un texte nettoyé en segments avec chevauchement."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    chunks = []
    start = 0
    while start < len(cleaned):
        end = start + chunk_size
        chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start += chunk_size - overlap
    return chunks


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Appelle l'API Embeddings configurée (ex. Jina v3 1024 dimensions) par lots."""
    if not settings.embed_api_key:
        raise RuntimeError("EMBED_API_KEY manquante dans l'environnement (.env).")
    resp = requests.post(
        settings.embed_base_url,
        headers={
            "Authorization": f"Bearer {settings.embed_api_key}",
            "Content-Type": "application/json",
        },
        json={"model": settings.embed_model, "input": texts},
        timeout=30,
    )
    _raise_for_api_error(resp, "Embeddings")
    data = resp.json()["data"]
    return [
        item["embedding"]
        for _, item in sorted(enumerate(data), key=lambda pair: pair[1].get("index", pair[0]))
    ]


def upsert_document(meta: dict) -> str:
    """Insère ou met à jour la fiche du document dans public.rag_documents et retourne son UUID."""
    base = settings.supabase_url.rstrip("/")
    endpoint = f"{base}/rest/v1/rag_documents?on_conflict=titre,editeur,date_publication"
    payload = {
        "titre": meta["titre"],
        "editeur": meta["editeur"],
        "date_publication": meta.get("date_publication"),
        "url_source": meta.get("url_source"),
        "langue": meta.get("langue", "fr"),
        "licence": meta.get("licence", "Usage interne uniquement"),
        "redistribution_ok": bool(meta.get("redistribution_ok", False)),
    }
    resp = requests.post(
        endpoint,
        headers=_supabase_headers("resolution=merge-duplicates,return=representation"),
        json=payload,
        timeout=20,
    )
    _raise_for_api_error(resp, "upsert rag_documents")
    return resp.json()[0]["id"]


def fetch_existing_hashes(document_id: str) -> dict[int, str]:
    """Récupère les hash existants (chunk_index -> content_hash) pour éviter de repayer l'API."""
    base = settings.supabase_url.rstrip("/")
    endpoint = f"{base}/rest/v1/rag_chunks"
    resp = requests.get(
        endpoint,
        headers=_supabase_headers(),
        params={"select": "chunk_index,content_hash", "document_id": f"eq.{document_id}"},
        timeout=20,
    )
    _raise_for_api_error(resp, "lecture rag_chunks")
    return {row["chunk_index"]: row["content_hash"] for row in resp.json()}


_REQUIRED_MANIFEST_FIELDS = ("filename", "titre", "editeur")


def validate_manifest(manifest_path: Path = MANIFEST_PATH, docs_dir: Path = DOCS_DIR) -> dict:
    """Valide le schéma de docs/manifest.json et vérifie la présence locale des fichiers déclarés."""
    if not manifest_path.exists():
        return {"status": "empty", "entries_count": 0, "present_files": [], "missing_files": [], "errors": []}
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("docs/manifest.json doit contenir une liste JSON d'entrées documentaires.")
    present: list[str] = []
    missing: list[str] = []
    errors: list[str] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append(f"Entrée #{idx} invalide (objet attendu).")
            continue
        for field in _REQUIRED_MANIFEST_FIELDS:
            if not str(entry.get(field) or "").strip():
                errors.append(f"Entrée #{idx} : champ obligatoire '{field}' manquant.")
        fname = str(entry.get("filename") or "").strip()
        if fname:
            if (docs_dir / fname).exists():
                present.append(fname)
            else:
                missing.append(fname)
    return {
        "status": "invalid" if errors else ("ok" if raw else "empty"),
        "entries_count": len(raw),
        "present_files": present,
        "missing_files": missing,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Indexation documentaire RAG FreeData.AI (Supabase pgvector).")
    ap.add_argument("--dry-run", action="store_true", help="Valide docs/manifest.json et liste les fichiers sans appel API.")
    args = ap.parse_args(argv)

    DOCS_DIR.mkdir(exist_ok=True)
    if not MANIFEST_PATH.exists():
        MANIFEST_PATH.write_text("[]\n", encoding="utf-8")
        print(f"[FreeData.AI RAG] Manifeste vierge créé dans {MANIFEST_PATH}. Aucun PDF à indexer.")
        return 0

    summary = validate_manifest(MANIFEST_PATH, DOCS_DIR)
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1 if summary["errors"] else 0

    if summary["errors"]:
        raise RuntimeError("Manifeste RAG invalide : " + " ; ".join(summary["errors"]))

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not manifest:
        print("[FreeData.AI RAG] Manifeste vide (0 PDF). Base vectorielle prête en attente de documents.")
        return 0

    base = settings.supabase_url.rstrip("/")
    chunks_endpoint = f"{base}/rest/v1/rag_chunks?on_conflict=document_id,chunk_index"

    for entry in manifest:
        pdf_path = DOCS_DIR / entry["filename"]
        if not pdf_path.exists():
            print(f"[FreeData.AI RAG] Fichier introuvable ignoré : {pdf_path}")
            continue

        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("Installez pypdf (pip install pypdf) pour indexer des PDF.") from exc

        doc_id = upsert_document(entry)
        existing_hashes = fetch_existing_hashes(doc_id)
        reader = PdfReader(str(pdf_path))

        pending = []
        idx = 0
        for page_num, page in enumerate(reader.pages, start=1):
            for segment in chunk_text(page.extract_text() or ""):
                h = hashlib.sha256(segment.encode("utf-8")).hexdigest()
                if existing_hashes.get(idx) != h:
                    pending.append({"page": page_num, "chunk_index": idx, "content": segment, "content_hash": h})
                idx += 1

        if idx == 0:
            print(f"[FreeData.AI RAG] Aucun texte extractible dans '{entry['titre']}' (PDF scanné sans couche texte ?).")
            continue

        if not pending:
            print(f"[FreeData.AI RAG] '{entry['titre']}' : déjà à jour (0 nouvel appel Embeddings).")
            continue

        # Traitement par lots de 16 extraits
        for i in range(0, len(pending), 16):
            batch = pending[i : i + 16]
            vectors = get_embeddings([b["content"] for b in batch])
            records = [
                {
                    "document_id": doc_id,
                    "page": b["page"],
                    "chunk_index": b["chunk_index"],
                    "content": b["content"],
                    "content_hash": b["content_hash"],
                    "embedding": vec,
                }
                for b, vec in zip(batch, vectors)
            ]
            resp = requests.post(
                chunks_endpoint,
                headers=_supabase_headers("resolution=merge-duplicates"),
                json=records,
                timeout=30,
            )
            _raise_for_api_error(resp, "insertion rag_chunks")

        print(f"[FreeData.AI RAG] '{entry['titre']}' : {len(pending)} extraits indexés.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())