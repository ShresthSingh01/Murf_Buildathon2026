# Medilo / MediSpeak

Medilo (MediSpeak) is a senior-friendly clinical dashboard application built to simplify complex medical PDF reports. By integrating high-end indexing, LLM summaries, and voice synthesis, it transforms complicated clinical diagnostics into clear, compassionate, and actionable advice that elderly users can actually understand.

## 🚀 Tech Stack Breakdown

The system relies on the following core technologies, each selected to accomplish a specialized component of the AI-driven pipeline:

*   **Python + Flask**  
    *Purpose*: Acts as the primary application framework. Routes web traffic, parses document uploads, and synchronizes the workflow between external APIs and background processing threads.
*   **PyMuPDF (`pymupdf`)**  
    *Purpose*: Rapidly processes uploaded clinical PDF reports to extract raw textual context perfectly intact, handling formatting idiosyncrasies effectively for base-level LLM ingestion.
*   **PageIndex SDK (`pageindex`)**  
    *Purpose*: Powers the cognitive Retrieval-Augmented Generation (RAG). It converts flat PDF data into a hierarchical reasoning tree, allowing highly accurate document traversal and answering specific patient Q&A queries without hallucinating.
*   **Google Gemini SDK & OpenRouter API**  
    *Purpose*: Handles text-to-JSON structuring, language translation (Hindi/English), and conversational summaries. Implements diverse models (Gemini 2.0 Flash, Llama 3) configured behind a "Circuit Breaker" to ensure massive resilience.
*   **Murf AI API (`murf`)**  
    *Purpose*: Drives the emotional computing piece of the application via hyper-realistic Text-To-Speech. Capable of generating high-fidelity accents tailored to the application's demographic (e.g., Hindi `hi-IN-rahul`, English `en-IN-rohan`).
*   **SQLite + Python OS (Session Store)**  
    *Purpose*: Acts as a lightning-fast caching and persistence layer (`.session_store.db`). Storing API outputs, report context hashes, and audio URLs substantially restricts repetitive API calls to Gemini and Murf logic limits.
*   **Vanilla HTML / CSS / JS**  
    *Purpose*: Provides a hyper-performant, single-page-app-like user interface heavily biased towards seniors (large fonts, contrasting metrics, simplified interaction design, minimal library overhead).

---

## 🛠 Prerequisites

Ensure you have the following ready in your environment:
- Python 3.10+
- An API Key for **Murf AI**
- An API Key for **PageIndex**
- *Optional/Highly Recommended*: API Keys for **Gemini** and **OpenRouter**

## 💻 Installation Steps

1. **Clone the Repository** \
   Navigate to the project directory:
   ```bash
   cd MurfProject
   ```

2. **Setup a Virtual Environment**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Mac/Linux:
   source .venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration**
   Copy the example environment securely and inject your credentials:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and configure:
   ```env
   MURF_API_KEY=your_murf_key_here
   PAGEINDEX_API_KEY=your_pageindex_key_here
   GEMINI_API_KEY=your_gemini_key_here
   OPENROUTER_API_KEY=your_openrouter_key_here
   ```

## 🏃 Usage Guide

1. **Booting the Server**
   Start the flask application by running:
   ```bash
   python app.py
   ```
2. **Accessing the Portal**
   Open your browser and navigate to `http://127.0.0.1:5000/`.

3. **Analyzing a Report**
   - Click the upload area to select a medical PDF document.
   - Choose your preferred language context (English / Hindi).
   - Press "Analyze Report".
   - The application will background process your document (text mapping -> PageIndex querying -> Synthesis -> Murf Audio buffering).
   - Once complete, you will be taken to a premium UI dashboard featuring simplified Clinical Metrics and a responsive AI Co-Pilot for further questioning.
