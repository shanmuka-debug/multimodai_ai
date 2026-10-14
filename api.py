"""HTTP API and production static-file host for the React study tutor."""

from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rag.chunking import chunk_pages
from rag.embeddings import load_embedding_model
from rag.fallback import is_overview_question
from rag.generator import GenerationError, generate_answer
from rag.pdf_loader import PDFLoadError, extract_pdf_pages
from rag.quiz import QuizError, generate_quiz
from rag.retriever import InMemoryIndex, build_index, retrieve, select_overview_passages

app = FastAPI(title="Study Tutor API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)

_documents: OrderedDict[str, tuple[InMemoryIndex, str]] = OrderedDict()
_documents_lock = RLock()
_max_documents = 5
_frontend_dist = Path(__file__).resolve().parent / "frontend" / "dist"


class QuestionRequest(BaseModel):
    document_id: str
    question: str = Field(min_length=1, max_length=2000)


class QuizRequest(BaseModel):
    document_id: str
    topic: str = Field(default="", max_length=180)
    difficulty: str = "Medium"


def _get_document(document_id: str) -> tuple[InMemoryIndex, str]:
    with _documents_lock:
        result = _documents.get(document_id)
        if result:
            _documents.move_to_end(document_id)
        return result


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/documents")
def upload_document(file: UploadFile = File(...)):
    filename = Path(file.filename or "study.pdf").name
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Please choose a PDF file.")
    contents = file.file.read(30 * 1024 * 1024 + 1)
    if len(contents) > 30 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="This PDF is larger than the 30 MB upload limit.")
    try:
        pages = extract_pdf_pages(contents, filename)
        chunks = chunk_pages(pages)
        if not chunks:
            raise PDFLoadError("No text passages could be created from this PDF.")
        index = build_index(chunks, model=load_embedding_model())
    except PDFLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not build the search index. Check dependencies and internet access for the first embedding-model download.",
        ) from exc

    document_id = uuid4().hex
    with _documents_lock:
        _documents[document_id] = (index, filename)
        while len(_documents) > _max_documents:
            _documents.popitem(last=False)
    return {
        "document_id": document_id,
        "document_name": filename,
        "page_count": len(pages),
        "chunk_count": len(chunks),
    }


@app.delete("/api/documents/{document_id}")
def clear_document(document_id: str):
    with _documents_lock:
        _documents.pop(document_id, None)
    return {"status": "cleared"}


@app.post("/api/chat")
def ask_question(request: QuestionRequest):
    document = _get_document(request.document_id)
    if not document:
        raise HTTPException(status_code=404, detail="This document session expired. Please upload the PDF again.")
    index, _ = document
    clean_question = request.question.strip()
    if not clean_question:
        raise HTTPException(status_code=400, detail="Type a question first.")
    try:
        results = retrieve(clean_question, index, top_k=4, model=load_embedding_model())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Passage search failed. Please try again.") from exc
    if not results:
        return {"answer": "I couldn't find relevant evidence in this document, so I can't answer from its contents.", "sources": []}

    overview = is_overview_question(clean_question)
    sources = select_overview_passages(index.chunks) if overview else results
    try:
        answer = generate_answer(clean_question, sources, overview=overview)
    except GenerationError as exc:
        answer = f"Answer generation unavailable: {exc} The retrieved passages are shown below."
    return {
        "answer": answer,
        "sources": [
            {"document_name": row.document_name, "page_number": row.page_number,
             "score": row.score, "text": row.text}
            for row in sources
        ],
    }


@app.post("/api/quiz")
def create_quiz(request: QuizRequest):
    document = _get_document(request.document_id)
    if not document:
        raise HTTPException(status_code=404, detail="This document session expired. Please upload the PDF again.")
    index, _ = document
    topic = request.topic.strip()
    try:
        if topic:
            sources = retrieve(topic, index, top_k=8, model=load_embedding_model())
        else:
            sources = select_overview_passages(index.chunks, max_pages=8)
        questions = generate_quiz(topic or "main ideas in the document", sources, request.difficulty)
    except (GenerationError, QuizError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not prepare the quiz. Try again.") from exc
    return {"topic": topic or "General", "difficulty": request.difficulty, "questions": [asdict(q) for q in questions]}


if _frontend_dist.is_dir():
    assets = _frontend_dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    candidate = (_frontend_dist / path).resolve()
    if _frontend_dist.is_dir() and candidate.is_relative_to(_frontend_dist.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    index_file = _frontend_dist / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return HTMLResponse(
        "<h1>React UI is not built yet</h1><p>In the frontend folder, run <code>npm install</code> and <code>npm run build</code>.</p>",
        status_code=503,
    )
