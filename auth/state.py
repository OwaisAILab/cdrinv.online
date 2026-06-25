# auth/state.py
"""
Shared in-memory user data store.
Used across main.py and auth/routes.py to avoid circular imports.
"""
_user_data = {}  # user_id -> { 'normalized': df, ... }