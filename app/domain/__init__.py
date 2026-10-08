"""Pure domain logic with no FastAPI or SQLAlchemy imports.

This boundary is deliberate: interleaving and fingerprinting are the parts
most likely to change or be reused, so they stay framework-free.
"""
