"""
Shared pytest configuration for all backend tests.

Problem
-------
Several SQLAlchemy models use PostgreSQL-specific column types:
- ``TSVECTOR`` — document_chunks.search_vector  (Sprint 12 FTS column)
- ``JSONB``    — messages.citations

SQLite (used in test fixtures for speed/isolation) does not support these
types.  Without a shim, ``Base.metadata.create_all()`` raises
``CompileError`` or ``UnsupportedCompilationError`` during test setup,
making the entire test suite fail.

Solution
--------
Register lightweight SQLite-compatible type compiler visitors for both types
before any test session begins.  The visitors map the PG-specific types to
their closest SQLite equivalents:
- TSVECTOR  → TEXT   (plain string; FTS queries are not exercised in unit tests)
- JSONB     → JSON   (SQLite has native JSON support in modern Python sqlite3)

This shim is only applied to the SQLite test engine; production PostgreSQL
databases are unaffected.

This file is auto-discovered by pytest as a session-wide conftest.
"""

from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.dialects.postgresql import TSVECTOR, JSONB


def _visit_TSVECTOR(self, type_, **kw):
    """Map PostgreSQL TSVECTOR → SQLite TEXT for test schema creation."""
    return "TEXT"


def _visit_JSONB(self, type_, **kw):
    """Map PostgreSQL JSONB → SQLite JSON for test schema creation."""
    return "JSON"


# Patch the SQLite type compiler once, at import time, for the entire test session.
SQLiteTypeCompiler.visit_TSVECTOR = _visit_TSVECTOR
SQLiteTypeCompiler.visit_JSONB = _visit_JSONB
