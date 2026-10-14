"""Streamlit interface for the local PDF RAG study tutor."""

import hashlib

import streamlit as st

from rag.chunking import chunk_pages
from rag.embeddings import load_embedding_model
from rag.fallback import is_overview_question
from rag.generator import GenerationError, generate_answer
from rag.learning import next_difficulty, revision_recommendations, summarize_performance
from rag.pdf_loader import PDFLoadError, extract_pdf_pages
from rag.quiz import QuizError, generate_quiz
from rag.retriever import build_index, retrieve, select_overview_passages

st.set_page_config(page_title="Study Tutor", page_icon="📚", layout="wide")
st.title("📚 AI Study Tutor")
st.caption("Ask questions about a text-based PDF and inspect the passages used to answer.")


def _source_title(source: dict) -> str:
    score = source.get("score")
    title = f"{source['document_name']} · page {source['page_number']}"
    return f"{title} · similarity {score:.3f}" if score is not None else title

for key, default in {
    "index": None, "document_id": None, "document_name": None, "messages": [],
    "quiz_attempts": [], "active_quiz": None,
}.items():
    st.session_state.setdefault(key, default)

with st.sidebar:
    st.header("Your study document")
    upload = st.file_uploader("Upload a PDF", type=["pdf"])
    fingerprint = hashlib.sha256(upload.getvalue()).hexdigest() if upload else None
    if fingerprint != st.session_state.document_id:
        st.session_state.index = None
        st.session_state.document_id = fingerprint
        st.session_state.document_name = None
        st.session_state.messages = []
        st.session_state.quiz_attempts = []
        st.session_state.active_quiz = None
    if st.button("Process PDF", type="primary", disabled=upload is None, use_container_width=True):
        try:
            with st.spinner("Extracting pages and building the search index…"):
                pages = extract_pdf_pages(upload.getvalue(), upload.name)
                chunks = chunk_pages(pages)
                if not chunks:
                    raise PDFLoadError("No text passages could be created from this PDF.")
                model = load_embedding_model()
                index = build_index(chunks, model=model)
                st.session_state.index = index
                st.session_state.document_id = fingerprint
                st.session_state.document_name = upload.name
                st.session_state.messages = []
                st.session_state.quiz_attempts = []
                st.session_state.active_quiz = None
            st.success(f"Indexed {len(chunks)} passages from {upload.name}.")
        except (PDFLoadError, ValueError) as exc:
            st.session_state.index = None
            st.error(str(exc))
        except Exception:
            st.session_state.index = None
            st.error(
                "Could not build the search index. Check that dependencies are installed and that "
                "internet access is available for the first embedding-model download, then try again."
            )
    if st.session_state.index:
        st.success(f"Ready: {st.session_state.document_name} · {len(st.session_state.index.chunks)} chunks")
        if st.button("Clear document and chat", use_container_width=True):
            st.session_state.index = None
            st.session_state.document_id = None
            st.session_state.document_name = None
            st.session_state.messages = []
            st.session_state.quiz_attempts = []
            st.session_state.active_quiz = None
            st.rerun()
    st.caption("Scanned image-only PDFs need OCR, which this version does not include.")
    st.caption("Free local answers use Ollama. Run `ollama pull llama3.2` once to download the model.")

chat_tab, practice_tab, dashboard_tab = st.tabs(["Ask the tutor", "Practice quiz", "Learning dashboard"])

with chat_tab:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            sources = message.get("sources", [])
            if sources:
                citation_map = " · ".join(
                    f"[S{i}] {source['document_name']}, page {source['page_number']}"
                    for i, source in enumerate(sources, 1)
                )
                st.caption(f"Sources: {citation_map}")
            for source in sources:
                with st.expander(_source_title(source)):
                    st.write(source["text"])

    question = st.chat_input("Ask about your processed PDF…", disabled=st.session_state.index is None)
    if question and st.session_state.index:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Finding relevant passages…"):
                    results = retrieve(question, st.session_state.index, top_k=4, model=load_embedding_model())
                    if not results:
                        answer = "I couldn't find relevant evidence in this document, so I can't answer from its contents."
                        source_rows = []
                    else:
                        overview = is_overview_question(question)
                        answer_sources = (
                            select_overview_passages(st.session_state.index.chunks)
                            if overview else results
                        )
                        try:
                            answer = generate_answer(question, answer_sources, overview=overview)
                        except GenerationError as exc:
                            answer = (
                                f"**Answer generation unavailable:** {exc}\n\n"
                                "The retrieved source passages are still available below."
                            )
                        source_rows = [
                            {"document_name": item.document_name, "page_number": item.page_number,
                             "score": item.score, "text": item.text} for item in answer_sources
                        ]
                st.markdown(answer)
                if source_rows:
                    citation_map = " · ".join(
                        f"[S{i}] {source['document_name']}, page {source['page_number']}"
                        for i, source in enumerate(source_rows, 1)
                    )
                    st.caption(f"Sources: {citation_map}")
                for source in source_rows:
                    with st.expander(_source_title(source)):
                        st.write(source["text"])
                st.session_state.messages.append({"role": "assistant", "content": answer, "sources": source_rows})
            except Exception:
                st.error("Search failed. Try the question again.")

with practice_tab:
    st.subheader("Practice from your PDF")
    st.caption("Questions include a checkable quote and PDF page. Results stay in this browser session.")
    topic = st.text_input("Topic (optional)", placeholder="For example: model training", disabled=st.session_state.index is None)
    if not st.session_state.index:
        st.info("Upload and process a PDF first.")
    else:
        difficulty = next_difficulty(topic.strip() or "General", st.session_state.quiz_attempts)
        st.caption(f"Suggested difficulty for **{topic.strip() or 'General'}**: {difficulty}")
        if st.button("Generate 3 questions", type="primary", key="generate_quiz"):
            try:
                with st.spinner("Finding passages and preparing questions…"):
                    if topic.strip():
                        quiz_sources = retrieve(topic.strip(), st.session_state.index, top_k=8, model=load_embedding_model())
                    else:
                        quiz_sources = select_overview_passages(st.session_state.index.chunks, max_pages=8)
                    questions = generate_quiz(topic.strip() or "main ideas in the document", quiz_sources, difficulty)
                st.session_state.active_quiz = {
                    "topic": topic.strip() or "General", "difficulty": difficulty,
                    "questions": [question.__dict__ for question in questions], "submitted": False,
                }
            except (QuizError, GenerationError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("Could not prepare the quiz. Check that the embedding model and Ollama are available, then try again.")

        quiz = st.session_state.active_quiz
        if quiz:
            if not quiz["submitted"]:
                with st.form("active_quiz"):
                    selections = []
                    for number, question_data in enumerate(quiz["questions"], 1):
                        st.markdown(f"**{number}. {question_data['question']}**")
                        selections.append(st.radio(
                            "Choose one answer", question_data["options"], index=None,
                            key=f"quiz_{number}_{len(st.session_state.quiz_attempts)}", label_visibility="collapsed",
                        ))
                    submitted = st.form_submit_button("Check answers")
                if submitted:
                    if any(selected is None for selected in selections):
                        st.warning("Choose an answer for each question before checking the quiz.")
                    else:
                        quiz["submitted"] = True
                        quiz["selected"] = selections
                        for question_data, selected in zip(quiz["questions"], selections):
                            correct_answer = question_data["options"][question_data["answer_index"]]
                            st.session_state.quiz_attempts.append({
                                "topic": quiz["topic"], "difficulty": quiz["difficulty"],
                                "correct": selected == correct_answer, "document_name": question_data["document_name"],
                                "page_number": question_data["page_number"], "question": question_data["question"],
                            })
                        st.rerun()
            else:
                for number, (question_data, selected) in enumerate(zip(quiz["questions"], quiz["selected"]), 1):
                    correct_answer = question_data["options"][question_data["answer_index"]]
                    st.markdown(f"**{number}. {question_data['question']}**")
                    if selected == correct_answer:
                        st.success(f"Correct. {question_data['explanation']}")
                    else:
                        st.info(f"Correct answer: {correct_answer}. {question_data['explanation']}")
                    st.caption(f"Evidence: “{question_data['evidence_quote']}” — {question_data['document_name']}, page {question_data['page_number']}")
                if st.button("Make another quiz", key="new_quiz"):
                    st.session_state.active_quiz = None
                    st.rerun()

with dashboard_tab:
    st.subheader("Your learning progress")
    attempts = st.session_state.quiz_attempts
    stats = summarize_performance(attempts)
    first, second, third = st.columns(3)
    first.metric("Questions answered", stats["answered"])
    second.metric("Correct answers", stats["correct"])
    third.metric("Overall accuracy", f"{stats['accuracy']:.0%}" if attempts else "—")
    if stats["topics"]:
        st.markdown("#### Accuracy by topic")
        st.bar_chart({topic_name: values["accuracy"] for topic_name, values in stats["topics"].items()})
        st.dataframe([
            {"Topic": topic_name, "Correct": values["correct"], "Answered": values["answered"],
             "Accuracy": f"{values['accuracy']:.0%}"}
            for topic_name, values in stats["topics"].items()
        ], hide_index=True, use_container_width=True)
        recommendations = revision_recommendations(attempts)
        if recommendations:
            st.markdown("#### Suggested review")
            for recommendation in recommendations:
                pages = ", ".join(f"{name}, page {page}" for name, page in recommendation["pages"])
                st.write(f"Review **{recommendation['topic']}** ({recommendation['accuracy']:.0%} correct): {pages}.")
    else:
        st.info("Complete a practice quiz to see topic progress and suggested revision pages.")
    st.caption("Progress is stored only in Streamlit's current session. It is cleared when the document changes or the session ends.")
