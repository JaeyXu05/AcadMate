# Paper Claw

Paper Claw is a local web application for paper discovery, document parsing, paper Q&A, and reading report generation.

## Requirements

Install the following tools first:

- Docker / Docker Compose: used to run PostgreSQL with pgvector
- Python 3.12+
- uv: used to install and run backend Python dependencies
- Node.js 20+ / npm: used to install and run frontend dependencies

## Database setup

The project root includes `docker-compose.yml`, which starts PostgreSQL 16 with the pgvector extension.

```bash
docker compose up -d
```

Default database settings:

```text
host: localhost
port: 5432
database: paper_claw
user: paper_claw
password: paper_claw
```

## Install dependencies

Run this command from the project root:

```bash
npm run setup
```

This installs:

- root npm dependencies
- frontend npm dependencies under `frontend`
- backend Python dependencies under `backend` with uv

## Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Fill in these required values:

```env
PAPER_CLAW_CHAT_API_KEY=
PAPER_CLAW_CHAT_BASE_URL=
PAPER_CLAW_CHAT_MODEL=
# The combined app also accepts CHATAGENT_API_KEY / CHATAGENT_BASE_URL / CHATAGENT_MODEL.

PAPER_CLAW_EMBEDDING_API_KEY=
PAPER_CLAW_EMBEDDING_BASE_URL=
PAPER_CLAW_EMBEDDING_MODEL=
PAPER_CLAW_EMBEDDING_HF_ENDPOINT=https://hf-mirror.com
PAPER_CLAW_EMBEDDING_HF_DISABLE_XET=true

PAPER_CLAW_OPENALEX_EMAIL=
PAPER_CLAW_OPENALEX_API_KEY=
PAPER_CLAW_LLAMA_PARSE_API_KEY=
```

Notes:

- `PAPER_CLAW_CHAT_*`: used for agent chat, paper Q&A, and report generation.
- `PAPER_CLAW_EMBEDDING_*`: used for paper content embeddings and evidence retrieval.
- The local FastEmbed model downloads from `hf-mirror.com` by default because
  `huggingface.co` is often unreachable from CN/campus networks. The backend
  falls back to Hugging Face automatically if the mirror is unavailable.
- arXiv search/download is keyless; its rate-limit settings use `PAPER_CLAW_ARXIV_*`.
- `PAPER_CLAW_OPENALEX_API_KEY` is optional. Set `PAPER_CLAW_OPENALEX_EMAIL` to a real contact address for the OpenAlex polite pool; otherwise the provider may return HTTP 429 under shared-IP traffic.
- `PAPER_CLAW_LLAMA_PARSE_API_KEY`: used for LlamaParse document parsing.

Do not commit a `.env` file containing real secrets.

## Start the app

After the database is running and `.env` is configured, run this command from the project root:

```bash
npm run prewarm
npm run dev
```

`npm run prewarm` downloads the local embedding model once and precomputes the
mentor vectors, so the first user does not pay that cost. `npm run dev` then
runs database migrations and starts both services:

- Backend API: `http://localhost:8000`
- Frontend dev server: Vite prints the actual URL in the terminal, usually `http://localhost:5173`
