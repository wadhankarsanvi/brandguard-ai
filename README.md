# BrandGuard AI — Intelligent Multimodal Brand Governance Platform

Pre-publication brand governance: upload brand guidelines once, then every draft (text, Markdown, PDF, PNG/JPEG) is
automatically checked, explained with **citations to the guideline**, fixed in one click, routed through a
**Creator → Brand Manager → Legal** approval hub, and finally stamped with a **cryptographic compliance badge**.
Analytics feed back into the guidelines themselves.

Implements the BrandGuard AI proposal (hybrid RAG + multimodal inspector, explainable suggestions, role-based approval hub,
analytics, privacy shield). A fictional brand, **Verdant**, is pre-loaded so the demo works on first boot.

---

## 1. Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m backend.app                                   # http://localhost:8000
```

Sign in with a demo account (password `BrandGuard@123`):

| Role | Email | Can do |
|---|---|---|
| Creator | `creator@brandguard.ai`, `creator2@brandguard.ai`, `agency@brandguard.ai` | submit, fix, dismiss, request review (sees only own work) |
| Brand manager | `manager@brandguard.ai` | review, manage rules/KB/palette, analytics, audit |
| Legal | `legal@brandguard.ai` | second-tier sign-off for claims/legal content |

Run the tests:
- Using Make: `make test` (or run server with `make run`, lint with `make lint`).
- **SQLite (default)**: `python -m unittest discover -s tests -v` (end-to-end test suite).
- **PostgreSQL**: set `DATABASE_URL` pointing to your test database before running:
  ```bash
  # Linux/macOS
  export DATABASE_URL="postgresql://user:password@localhost:5432/brandguard_test"
  python -m unittest discover -s tests -v

  # Windows (PowerShell)
  $env:DATABASE_URL="postgresql://user:password@localhost:5432/brandguard_test"
  python -m unittest discover -s tests -v
  ```

**Try this demo flow:** sign in as Aisha → *New check → Load sample draft* → watch the issues, apply fixes, try *Preview AI-assisted rewrite*
→ *Submit for review* (PII must be fixed first) → sign in as Maya (manager) → *Review queue* → approve → Legal (Rohan) approves →
copy the badge from the *Review & comments* tab into *Verify badge*. Then edit the content as manager and verify again: the badge becomes invalid.
Upload a banner PNG to see colour, contrast and alt-text checks with boxes drawn on the image.

---

## 2. Deploy on Render (free)

1. Push this folder to a GitHub repository.
2. Render dashboard → **New → Blueprint** → select the repo. `render.yaml` configures everything
   (build `pip install -r requirements.txt`, start `gunicorn backend.app:app`, health check `/api/health`, generated `SECRET_KEY`).
   *(Or **New → Web Service**, runtime Python, same build/start commands.)*
3. Open the service URL, sign in with a demo account.

Environment variables: see `.env.example`. Notes:
- **Database**: PostgreSQL is configured automatically via `render.yaml` using a free Render PostgreSQL database and `DATABASE_URL`. Locally, it defaults to SQLite (`data/brandguard.db`).
- **Free plan disk is ephemeral** — Uploads reset on redeploy/sleep; demo data is re-seeded automatically.
  For upload persistence use a paid plan + disk mounted at `/var/data` and set `DATA_DIR=/var/data`.
- Keep **one gunicorn worker** (as configured) – the demo uses SQLite.
- Set `SEED_DEMO_DATA=false` for an empty production instance (users/rules/KB are still seeded; change `DEMO_PASSWORD`).
- Optional `ANTHROPIC_API_KEY` switches on LLM rewriting and vision claim co-verification. Without it everything runs on the deterministic engine.
- Optional `EMBEDDINGS=on` enables dense semantic embeddings via `fastembed` (`BAAI/bge-small-en-v1.5`) combined with TF-IDF (install via `pip install -r requirements-embeddings.txt`). If unset or uninstalled, falls back to lightweight in-process TF-IDF.

---

## 3. Architecture

```
 Browser SPA (vanilla JS, hash router, canvas annotations)
        │  JSON / multipart over HTTPS, JWT bearer
        ▼
 Flask API (backend/app.py)  ──────────────  serves frontend/ as static files (one Render service)
   routes/auth_kb.py       auth · knowledge base · rules · settings · analytics · audit · /verify
   routes/submissions.py   submissions · issues(apply/dismiss) · diff · comments · review
        │
   services/
     rag.py             chunking + TF-IDF (uni+bigram) vector index, cosine search      ← Stage 1 ingestion / retrieval
     text_checker.py    terminology · tone · claim verification · disclaimers · PII      ← NLP engine
     image_checker.py   OpenCV: palette ΔE (Lab k-means) · WCAG contrast · alt text ·
                        logo clear-space · text↔image co-verification                    ← Vision engine
     pipeline.py        runs both engines, stores issues, scores, builds rewrites        ← Stage 2
     workflow.py        review state machine (manager → legal), revisions                ← Stage 3
     badge.py           HMAC-SHA256 compliance badge bound to the exact content hash     ← Stage 4
     analytics.py       KPIs, team scores, ambiguous-guideline detector                  ← Stage 4
     llm.py             OPTIONAL Claude call (rewrite + vision); PII masked first
        │
 SQLite (stdlib sqlite3, WAL) — users, documents/chunks, rules, submissions, revisions, issues, comments, approvals, audit
```

### How it works (the 4-stage lifecycle from the proposal)

1. **Knowledge ingestion** – Managers upload PDF/MD/TXT guidelines, product facts, glossaries. Text is split into heading-aware
   chunks and indexed in a TF-IDF vector index (rebuilt lazily when chunks change). Brand rules (regex terminology, tone limits,
   claim triggers, required disclaimers) live in a `rules` table, each pointing to its guideline section.
2. **Automated analysis** – On submit, the pipeline runs:
   - *Text*: terminology swaps, hype/ALL-CAPS/exclamation tone checks, readability, PII detection (email/phone/card), required disclaimers,
     and **claim verification**: each claim sentence is retrieved against the knowledge base; it passes only if retrieval score,
     keyword coverage **and every number** match the source (so “36 hours” fails against “24 hours”). Result: either a *verified claim* with its
     evidence, or an issue citing the nearest passage — claims are never “verified” by an LLM guess (anti-hallucination design).
   - *Image*: dominant colours vs. the brand palette (ΔE in CIELAB), WCAG contrast of detected text regions, resolution, alt-text quality,
     logo clear-space (if a logo is uploaded), plus **multimodal co-verification** (e.g. “eco-friendly packaging” vs. visible green/kraft cues; a vision LLM is used if a key is set).
   - A 0–100 compliance score (severity-weighted, capped per rule) and issue list with character offsets / bounding boxes.
3. **Collaborative review** – Creators apply a fix, dismiss a flag (reason feeds analytics), edit text, or preview a full **intent-preserving rewrite**
   (only flagged problems are changed; AI disclosure shown). Submit → manager → legal (automatically required if claims/legal issues exist).
   Threaded comments, word-level visual diff between revisions, full audit trail, critical issues (PII) block submission/approval.
4. **Publish & insights** – Approval issues a signed badge `BG1.<payload>.<hmac>`; `/api/verify` checks the signature **and** that content is unchanged.
   Dashboard shows violations by rule, category, team scorecard, trend, and the **guideline feedback loop**: rules hit by many creators *and*
   frequently dismissed are flagged as probably ambiguous.

### Design choices & deviations from the proposal’s stack
| Proposal | This build | Why |
|---|---|---|
| FastAPI | **Flask** + gunicorn | Same role (REST backend); runs as a single Render service. |
| Next.js + Tailwind + shadcn + TanStack Query | **Vanilla JS SPA** served by Flask | No Node build step → deploys in one click. |
| Fabric.js annotations | HTML canvas boxes | Enough for read-only annotation; swap later for editing. |
| Vector DB / embeddings | In-process TF-IDF index | No model download/memory cost on free tier; `rag.search()` is the single seam to replace with pgvector/Chroma. |
| VLM | OpenCV heuristics + optional Claude vision | Works offline; LLM upgrades it. |

---

## 4. Project structure

```
brandguard/
├── README.md  render.yaml  requirements.txt  Procfile  .env.example  .python-version
├── backend/
│   ├── app.py  config.py  db.py  common.py  seed.py
│   ├── routes/    auth_kb.py  submissions.py
│   └── services/  rag.py  text_checker.py  image_checker.py  pipeline.py  workflow.py  badge.py  analytics.py  llm.py  pdf.py
├── frontend/      index.html  css/style.css  js/app.js
├── sample_data/   brand_guidelines.md  product_facts.md  drafts/*.md   (loaded on first boot)
├── tests/         test_api.py
└── data/          SQLite DB + uploads (created at runtime)
```

### API overview
`POST /api/auth/login` · `GET/POST/DELETE /api/kb/documents` · `GET /api/kb/search?q=` · `GET/POST/PUT/DELETE /api/rules` ·
`GET/POST /api/submissions` · `GET /api/submissions/:id` · `POST …/issues/:iid/{apply,dismiss,reopen}` · `PUT …/content` ·
`GET …/rewrite` · `POST …/apply-all` · `GET …/diff?from=&to=` · `POST …/comments` · `POST …/submit-review` · `POST …/review` ·
`GET /api/analytics` · `GET /api/audit` · `GET /api/verify?token=` (public).

---

## 5. Status — what is done and what is left

**Working (~65%)**: auth & roles, KB ingestion + retrieval, rule engine, text + image analysis, claim verification with citations,
fix/dismiss/rewrite, revisions & diff, comments, two-tier approval, signed badges, analytics with ambiguity detection, audit log, responsive UI, tests, Render config.

**Natural next steps**: Postgres + pgvector (persistence/scale), real embeddings, per-guideline version history, email/Slack notifications,
in-canvas editing of image annotations (Fabric.js), PDF page-level highlights, video frames, Figma/WordPress plugins, SSO instead of demo accounts,
rate limiting, background jobs for heavy files.
