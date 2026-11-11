"""Central configuration. Every value can be overridden with an environment variable."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.getenv("DATABASE_URL")
FRONTEND_DIR = BASE_DIR / "frontend"
SAMPLE_DIR = BASE_DIR / "sample_data"

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
LOGO_DIR = DATA_DIR / "logos"
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "brandguard.db"))

DEFAULT_SECRET_KEY = "dev-only-secret-change-me-before-deploying-123"
SECRET_KEY = os.getenv("SECRET_KEY", DEFAULT_SECRET_KEY)
TOKEN_TTL_HOURS = int(os.getenv("TOKEN_TTL_HOURS", "12"))
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "BrandGuard@123")
SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "true").lower() == "true"

# Optional embedding backend (fastembed BAAI/bge-small-en-v1.5)
EMBEDDINGS = os.getenv("EMBEDDINGS", "off").lower() in ("on", "true", "1")

# Optional LLM / VLM layer. Without a key the platform runs fully on the
# deterministic rule + RAG engine, so it always works offline and on free tiers.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))

for d in (DATA_DIR, UPLOAD_DIR, LOGO_DIR):
    d.mkdir(parents=True, exist_ok=True)
