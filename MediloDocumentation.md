# Medilo: Comprehensive System Documentation

## 1. Introduction & Overview

Medilo (also configured as MediSpeak in the frontend) is a compassionate medical report analysis platform designed specifically with senior citizens in mind. The primary goal of the system is to take complex, clinical medical reports (PDF format), extract the data, and transform it into an easy-to-understand narrative. The system combines Advanced Reasoning RAG, multi-layered Large Language Model failovers, and intelligent Voice Synthesis to deliver a clear, accessible, and interactive experience for elderly patients.

---

## 2. Complete System Working (User Journey)

The application follows a streamlined end-to-end event-driven architecture starting from the user's browser down to backend AI pipelines.

1. **Upload Phase**: The user uploads a medical PDF report via the web interface and selects a preferred language (English or Hindi).
2. **Background Processing**: The Flask server creates a unique session UUID for the report and immediately detaches the heavy AI process into a background PyThread, returning a "Processing" status to the client, which enters an `analyzing.html` loading loop.
3. **Information Extraction**: `PyMuPDF` parses the raw textual data from the document.
4. **Cognitive Indexing**: The document file is submitted to the **PageIndex Cloud API**, which builds an intelligent tree structure of the clinical data.
5. **AI Summarization & Structuring**: 
   - A language model is tasked with generating a structured JSON output mapped to a senior-friendly schema (Narrative Summary, Clinical Metrics, Urgent Actions).
   - This relies primarily on the PageIndex Document chat. If that fails or times out, it falls back to a custom Gemini/OpenRouter generation pipeline utilizing the raw text context.
6. **Voice Synthesis Execution**: The extracted narrative summary is passed to the **Murf AI** Text-To-Speech (TTS) SDK to generate an MP3 audio file with local region accents (e.g., `hi-IN-rahul` or `en-IN-rohan`).
7. **Session Storage**: The entire context (JSON, extracted text, Document ID, Audio URL) is cached securely in a local SQLite database (`.session_store.db`).
8. **Interactive Dashboard View**: The patient is seamlessly redirected to the dashboard view where dynamic metric cards and Murf AI-generated audio explain the results in plain English or Hindi.
9. **Interactive Follow-up (Q&A)**: Users can ask questions about the report. The backend queries PageIndex first for an indexed answer, falls back to raw-text Gemini RAG, and finally relies on general medical knowledge if all context fails. 

---

## 3. Core Techniques & Technical Features

### A. Multi-Layered RAG (Retrieval-Augmented Generation)
Medilo doesn't rely on a single point of failure for reading medical reports. The Question-Answering (Q&A) pipeline uses a 3-level approach:
- **Level 1 (PageIndex Tree RAG)**: Sends the query against the dynamically generated tree indexed via the `pageindex` SDK for pinpoint accuracy based heavily on reasoning.
- **Level 2 (High-Fidelity Raw Text RAG)**: If Level 1 fails, the full raw text is injected directly into the Gemini/OpenRouter context window for an in-context synthesis.
- **Level 3 (General Backend Knowledge)**: The system defaults to general medical AI knowledge with a strict system prompt emphasizing user safety ("Consult a doctor") if specific patient context drops.

### B. Intelligent API Circuit Breaker
Since Medilo coordinates multiple Generative AI models (Gemini Flash, Llama 3 on OpenRouter), it implements a custom Circuit Breaker pattern. If an AI endpoint times out or fails 3 consecutive times, it is temporarily locked out (Cooldown: 5 minutes). Traffic is flawlessly routed to the next available OpenRouter/Gemini backup model seamlessly.

### C. Persistent Session Caching & Rate Limiting
To prevent abuse and minimize API costs (specifically Murf and LLMs):
- **Database Caching**: Every Q&A interaction's hash and TTS output URL is stored in SQLite. If a patient asks the same question or triggers the same summary, Medilo immediately returns the cached output.
- **Rate Limiting**: An in-memory queue restricts requests to protect the API perimeters (Max 10 questions per report/minute).
- **TTS Length Checks**: Extremely short TTS outputs bypass Murf AI logic and fallback to Browser-level Voice APIs to save audio generation credits.

### D. Medical Biomarker Normalization
Medilo uses a local `biomarkers.json` file as a deterministic Knowledge Base. Clinical variations of medical acronyms (e.g., "LDL", "Low-Density Lipoprotein", "Bad Cholesterol") are instantly mapped to a canonical key format, ensuring exact labeling and matching across the frontend UI.

### E. Background AI Handlers & Polling
To navigate HTTP timeouts common to AI applications, file ingestion runs on Python background daemon threads. The frontend `analyzing` screen uses HTTP Long Polling to query the backend route (`/status/<report_id>`) until processing dictates a `<Ready>` state map.

---

## Summary
By combining resilient LLM failovers, cognitive document indexing (PageIndex), human-like vocal rendering (Murf AI), and senior-specific constraints, Medilo guarantees an informative, empathetic, and reliable clinical understanding experience for elderly patients.
