# AI Study Tutor (RAG prototype)

A polished React study app with a Python RAG API. It extracts selectable PDF text, finds relevant passages with a pretrained sentence embedding model, writes cited answers with Ollama or Gemini, and offers PDF-grounded practice quizzes, learning progress, and a personal notes workspace. Notes autosave locally in the browser and can be searched, pinned, and exported. The profile menu lets students set a display name and clear the current study session. The earlier Streamlit interface remains available as a fallback.

## Requirements and setup (Windows PowerShell)

Python 3.14.3 and the existing project `.venv` were verified during setup. Streamlit's current install guide lists Python 3.10–3.14 as supported. In a new VS Code terminal, from this folder, activate the existing environment:

```powershell
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install -r requirements.txt
```

Only if `.venv` does not exist yet, create it first with `py -m venv .venv`.

If activation is blocked by PowerShell policy, do not change the machine-wide policy. Use the venv interpreter directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

In VS Code, select `.venv\Scripts\python.exe` with **Python: Select Interpreter** (install the Microsoft Python extension if that command is missing).

## Free local answer generation (Ollama)

The app uses Ollama on your computer when `GEMINI_API_KEY` is not set. Install [Ollama for Windows](https://ollama.com/download/windows), then open PowerShell and download the default model once:

```powershell
ollama pull llama3.2
```

Keep the Ollama app running while using the tutor. The app calls Ollama at `http://localhost:11434`; PDF passages stay on this computer for generation. There is no per-request API fee, but the model download uses disk space and answers use your computer's memory and processing power. Set `OLLAMA_MODEL` in `.env` if you downloaded a different Ollama model.

## Run in Docker on Windows

Install and start Docker Desktop. Ollama must remain installed and running on the Windows host, with the model downloaded:

```powershell
ollama pull llama3.2
```

From the project folder, build and start the app:

```powershell
docker compose up --build
```

Open `http://localhost:8501`. Docker builds and serves the React interface with the Python API. The Compose configuration connects the container to the host's Ollama API through `host.docker.internal`. The first image build installs dependencies, and the first app run downloads the embedding model; both can take a while. The named `huggingface_cache` volume keeps that model between container restarts. Stop the app with Ctrl+C, or run `docker compose down` in another PowerShell window.

Gemini remains optional. If you want it in Docker, create `.env` from `.env.example` and put the key there; Compose passes it to the container. Never put secrets in the Dockerfile or commit `.env`. The `.dockerignore` keeps `.env`, `.venv`, PDFs, and tests out of the image build context.

This setup is for a Docker container running on the same PC as Ollama. If you deploy the container to a public cloud or another computer, `host.docker.internal` points to that server, not to your Windows PC. That server then needs its own reachable Ollama service or a configured Gemini key. Do not expose Ollama's unauthenticated API directly to the public internet.

## Optional Gemini key

If you prefer Gemini, create a key at [Google AI Studio](https://aistudio.google.com/) and make a local copy of the example file:

```powershell
Copy-Item .env.example .env
```

Then edit `.env` and add the key only there:

```text
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.8-flash
```

When `GEMINI_API_KEY` is configured, the app uses Gemini instead of Ollama. Never paste a private key into chat or commit `.env`. Model access and quotas depend on the Google account and can change; this app does not enable billing automatically.

## Run the React app

Start the API in one PowerShell terminal from the project folder:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --reload --port 8000
```

In a second terminal, start Vite:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:5173`. Current Vite needs Node.js 20.19+ or 22.12+. Use `npm.cmd` in PowerShell if script policy blocks `npm.ps1`. Stop either server with Ctrl+C.

For a production-style local run, build the frontend and serve it through the API:

```powershell
cd frontend
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8501
```

The existing Streamlit interface can still be launched separately:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Run automated tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The regular tests run offline with generated PDFs and fake model/API responses. After the first successful model download, you can also run the opt-in real MiniLM smoke tests in PowerShell:

```powershell
$env:RUN_REAL_MINILM_SMOKE = "1"
.\.venv\Scripts\python.exe -m pytest -q tests\test_real_model_smoke.py
Remove-Item Env:RUN_REAL_MINILM_SMOKE
```

## How the pipeline works

**PDF → text extraction → chunking → embeddings → retrieval → grounded prompt → local Ollama or optional Gemini answer with source labels.** PyMuPDF extracts each page and retains its one-based page number. Chunking creates passages about 900 characters long with 150 characters of overlap. The overlap preserves nearby context at boundaries; chunk size trades passage focus against broader context. MiniLM turns text into a vector: passages with similar meaning tend to have vectors pointing in similar directions. The retriever compares normalized vectors using a dot product and returns the highest scoring passages. Scores measure similarity, not truth. The language model sees only a few retrieved passages, with instructions to treat them as untrusted source text and cite provided labels. Prompt instructions reduce risk but cannot guarantee factual answers.

The **embedding model** maps text to vectors; the **retriever** searches those vectors; the **language model** writes a response; **RAG** is the process of retrieving evidence before generation. Embeddings are local and separate from Gemini. The MiniLM model downloads to the computer on first use and needs internet and disk space then. With no Gemini key, answers use the local Ollama model. Broad overview questions use page-spread excerpts so the model can describe the document more generally; specific questions use similarity-ranked passages. Retrieval scores rank passages and are not confidence scores. The React interface is built with Vite, uses Motion for transitions, and communicates with FastAPI; React and Streamlit share the same RAG modules.

## Practice and learning progress

After processing a PDF, open **Practice quiz**. Enter a topic to retrieve relevant passages, or leave the topic empty for page-spread coverage. The tutor asks Ollama or Gemini for three multiple-choice questions. A question is shown only if its quoted supporting passage can be matched to retrieved PDF text; its answer view includes the original document name and page number. Review the evidence passage yourself because a language model can still make a mistake about what a quote means.

The **Learning dashboard** summarizes correct answers and accuracy by topic, then points to pages associated with missed questions. Suggested difficulty starts at Medium and changes after at least three answers for that topic: at 80% or higher it steps up one level, below 50% it steps down, and otherwise it stays the same. Difficulty is limited to Easy, Medium, and Hard. These are simple practice rules, not a validated assessment of mastery.

Quiz results are held in Streamlit session state only. They are not written to disk or shared across browsers, and are cleared when the processed document changes, the app session is restarted, or the user clears the document. This prototype has no login or long-term student record.

## Personal notes and profile

Open **My notes** from the main navigation to create notes, edit titles and text, search notes, pin important notes, or export a note as a plain-text file. Notes autosave to this browser's local storage and remain after a page reload on the same browser profile. They are not synced between devices and are not uploaded to the API. New notes remember the currently selected PDF name as a reference; this does not attach the PDF contents to the note. Click the profile circle to set the displayed student name, create a note, or clear the current PDF and quiz session. Clearing the study session keeps saved notes.

## Files

- `app.py`: Streamlit workflow and session state.
- `api.py`: FastAPI endpoints used by React; short-lived document indexes stay in server memory.
- `frontend/`: Vite + React interface, Motion transitions, and Lucide icons.
- `rag/pdf_loader.py`: PDF text extraction and scan/invalid-file errors.
- `rag/chunking.py`: text windows with page/document metadata.
- `rag/embeddings.py`: lazy local MiniLM inference.
- `rag/retriever.py`: NumPy in-memory similarity search.
- `rag/generator.py`: local Ollama generation or optional Gemini API, isolated from retrieval.
- `Dockerfile`, `compose.yaml`, `.dockerignore`: multi-stage React build and local Docker Compose setup.
- `rag/quiz.py`: quiz creation and validation of cited evidence quotes.
- `rag/learning.py`: session-level progress summaries, adaptive difficulty, and review suggestions.
- `tests/`: offline unit and end-to-end tests using generated PDFs and fake embeddings/API responses, including quiz validation and progress rules.
- `tests/test_real_model_smoke.py`: opt-in checks using the actual pretrained model, including generated-PDF retrieval; skipped by the normal offline test run.

The dependencies each have one job: React and Vite build the main interface; FastAPI and Uvicorn provide its local API; Motion animates transitions and Lucide supplies icons; Streamlit remains as a fallback interface; PyMuPDF reads PDF text; Sentence Transformers and its PyTorch runtime produce local embeddings; NumPy stores vectors and computes similarity; google-genai calls Gemini when a key is configured; Python's standard library calls Ollama locally; python-dotenv loads the local `.env`; pytest runs the offline checks.

## Models, sources, and limits

- `sentence-transformers/all-MiniLM-L6-v2`: English sentence similarity model, Apache-2.0 on its Hugging Face model card. Its card describes 384-dimensional vectors and a 256 word-piece input limit; long chunks may be truncated by the model. This first pass targets English text, not multilingual material.
- Ollama uses the local model configured by `OLLAMA_MODEL`, defaulting to `llama3.2`. It runs on the computer and does not require a hosted API key.
- Gemini text generation uses Google's `google-genai` SDK. Set `GEMINI_MODEL` to a model your key can access; the current default is `gemini-3.8-flash` according to Google's model catalogue. API calls need network access and are subject to account access, quotas, and possible charges under Google account terms.
- This version supports one current PDF index in memory, selectable text only, no OCR, no persistent vector database, no login, and session-only learning progress. Similarity ranking and citations should be checked against the passages; generated answers and quiz keys can still be wrong.

## Troubleshooting

- **Activation is blocked:** use the direct `.venv\Scripts\python.exe` commands above.
- **First indexing is slow:** Sentence Transformers downloads model files on first use; allow network access and disk space.
- **Ollama answers unavailable:** open the Ollama app and run `ollama pull llama3.2` in PowerShell; set `OLLAMA_MODEL` if using a different model.
- **Docker cannot reach Ollama:** verify Ollama is running on Windows and that `OLLAMA_BASE_URL` in `compose.yaml` is `http://host.docker.internal:11434/api/chat`.
- **No text found:** the PDF may be scanned images; OCR is a future feature.
- **Invalid key or quota message:** verify `.env` variable spelling and model access in AI Studio; the app does not switch models or enable billing automatically.
- **PDF upload error:** export a valid PDF with selectable text and try again.
- **Missing imports:** activate `.venv` and install `requirements.txt` using that interpreter.

## References

- [Python virtual environments](https://docs.python.org/3/library/venv.html)
- [Streamlit installation](https://docs.streamlit.io/get-started/installation)
- [PyMuPDF basics](https://pymupdf.readthedocs.io/en/latest/the-basics.html)
- [Sentence Transformers quickstart](https://sbert.net/docs/quickstart.html)
- [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- [Gemini API get started](https://ai.google.dev/gemini-api/docs/get-started)
- [Gemini models](https://ai.google.dev/gemini-api/docs/models)
