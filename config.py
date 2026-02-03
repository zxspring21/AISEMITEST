"""Configuration for STDF DB and app."""
import os

# Database URL (SQLite by default; set STDF_DB_URL for PostgreSQL etc.)
DATABASE_URL = os.getenv("STDF_DB_URL", "sqlite:///stdf_data.db")

# Optional: default company/product/stage when not in STDF
DEFAULT_COMPANY = os.getenv("STDF_DEFAULT_COMPANY", "DefaultCompany")
DEFAULT_PRODUCT = os.getenv("STDF_DEFAULT_PRODUCT", "")
DEFAULT_STAGE = os.getenv("STDF_DEFAULT_STAGE", "")
