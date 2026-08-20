"""Shared Pydantic contracts consumed by more than one pipeline stage.

Single source of truth so Stage 1A and Stage 1B (built independently, on
separate branches) never end up with two slightly different definitions of
the same model. Both stage modules import from here rather than redefining
these classes locally.
"""
