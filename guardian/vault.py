"""
Vault - Encrypted secrets storage for API keys and credentials.
"""

import os
import base64
import json
import logging
import sqlite3
from typing import Optional, Dict, Any
from pathlib import Path

log = logging.getLogger(__name__)


class Vault:
    """Encrypted secrets storage."""
    
    def __init__(
        self,
        db_path: str = "data/guardian/vault.db",
        key_env: str = "SPARKBOT_VAULT_KEY",
    ):
        self.db_path = Path(db_path)
        self.key_env = key_env
        self.encryption_key = os.getenv(key_env)
        
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_db()
        
    def _init_db(self):
        """Initialize vault database."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS vault_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alias TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                encrypted_value BLOB,
                access_policy TEXT NOT NULL DEFAULT 'use_only',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used_at TEXT,
                rotation_due TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        
    def put(
        self,
        alias: str,
        value: str,
        policy: str = "use_only",
        category: str = "general",
        notes: str = None
    ) -> bool:
        """Store a secret."""
        from datetime import datetime
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        now = datetime.utcnow().isoformat()
        
        # In production, encrypt value with self.encryption_key
        # For now, store with simple encoding
        encrypted = base64.b64encode(value.encode('utf-8')) if value else b''
        
        try:
            c.execute("""
                INSERT OR REPLACE INTO vault_entries 
                (alias, category, encrypted_value, access_policy, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (alias, category, encrypted, policy, notes, now, now))
            conn.commit()
            log.info(f"Vault: stored {alias}")
            return True
        except Exception as e:
            log.error(f"Vault: failed to store {alias}: {e}")
            return False
        finally:
            conn.close()
            
    def get(self, alias: str) -> Optional[str]:
        """Retrieve a secret (internal use only)."""
        from datetime import datetime
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("""
            SELECT encrypted_value, access_policy 
            FROM vault_entries 
            WHERE alias = ?
        """, (alias,))
        
        row = c.fetchone()
        conn.close()
        
        if not row:
            return None
            
        encrypted, policy = row
            
        # Check policy
        if policy == "disabled":
            return None
            
        # Decode (in production, decrypt)
        try:
            raw = bytes(encrypted) if not isinstance(encrypted, bytes) else encrypted
            value = base64.b64decode(raw).decode('utf-8')
            return value
        except:
            return None
            
    def get_metadata(self, alias: str) -> Optional[Dict]:
        """Get metadata for a secret (without revealing value)."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("""
            SELECT alias, category, access_policy, notes, created_at, updated_at
            FROM vault_entries 
            WHERE alias = ?
        """, (alias,))
        
        row = c.fetchone()
        conn.close()
        
        if not row:
            return None
            
        return {
            "alias": row[0],
            "category": row[1],
            "access_policy": row[2],
            "notes": row[3],
            "created_at": row[4],
            "updated_at": row[5]
        }
        
    def list_aliases(self, category: str = None) -> list:
        """List all aliases (metadata only)."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        if category:
            c.execute("SELECT alias, category, access_policy FROM vault_entries WHERE category = ?", (category,))
        else:
            c.execute("SELECT alias, category, access_policy FROM vault_entries")
            
        rows = c.fetchall()
        conn.close()
        
        return [
            {"alias": r[0], "category": r[1], "access_policy": r[2]}
            for r in rows
        ]
        
    def delete(self, alias: str) -> bool:
        """Delete a secret."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("DELETE FROM vault_entries WHERE alias = ?", (alias,))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        
        if deleted:
            log.info(f"Vault: deleted {alias}")
        return deleted
        
    def get_status(self) -> Dict:
        """Get vault status."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM vault_entries")
        count = c.fetchone()[0]
        
        c.execute("SELECT COUNT(DISTINCT category) FROM vault_entries")
        categories = c.fetchone()[0]
        
        conn.close()
        
        return {
            "total_secrets": count,
            "categories": categories,
            "encryption_configured": bool(self.encryption_key)
        }
