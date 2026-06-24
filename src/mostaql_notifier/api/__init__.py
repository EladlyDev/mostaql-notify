"""FastAPI dashboard backend (Feature 2).

Read-mostly JSON API over Feature 1's local SQLite database. Reuses the existing SQLAlchemy
models/session as the single source of truth; the only write path is ``PUT /api/settings``.
No endpoint ever triggers a scrape or notification (constitution IV / read-only guarantee).
"""
