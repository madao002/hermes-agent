#!/usr/bin/env python3
"""
Holographic Memory Tool - Vector-based Memory Search

Provides holographic memory for Hermes Agent using HRR (Holographic Reduced Representations).
Features:
  - add: Add a key-value memory
  - recall: Get exact value by key
  - search: Semantic search using vector similarity
  - get_all: List all memories
  - delete: Delete a memory
  - stats: Get memory statistics
"""

import json
import logging
import os
import sys
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Add venv src path for holographic_memory (cross-platform)
import sysconfig
_VENV_SRC = os.path.join(sysconfig.get_paths()["purelib"], "src")
if _VENV_SRC not in sys.path:
    sys.path.insert(0, _VENV_SRC)

from holographic_memory import HolographicMemory

# Singleton instance
_hm_instance: Optional['HermesHolographicMemory'] = None


class HermesHolographicMemory:
    """Holographic Memory wrapper with file persistence."""

    def __init__(self, vector_size: int = 512, seed: int = 42):
        self.hm = HolographicMemory(vector_size=vector_size, seed=seed)
        self.storage_path = os.path.expanduser("~/.hermes/holographic_memory.json")
        self._memories: Dict[str, str] = {}
        self._vectors: Dict[str, tuple] = {}  # key -> (key_vec, value_vec)
        self._load()

    def add(self, key: str, value: str) -> bool:
        """Add a memory entry."""
        try:
            key_vec = self.hm.create_vector(key)
            value_vec = self.hm.create_vector(value)
            self._memories[key] = value
            self._vectors[key] = (key_vec, value_vec)
            self._save()
            return True
        except Exception as e:
            logger.error(f"Failed to add memory: {e}")
            return False

    def recall(self, key: str) -> Optional[str]:
        """Recall exact value by key."""
        return self._memories.get(key)

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search memories by semantic similarity."""
        results = []
        try:
            query_vec = self.hm.create_vector(query)
            for key, value in self._memories.items():
                key_vec, value_vec = self._vectors[key]
                sim_key = self.hm.similarity(query_vec, key_vec)
                sim_value = self.hm.similarity(query_vec, value_vec)
                sim = max(sim_key, sim_value)
                results.append({'key': key, 'value': value, 'similarity': float(sim)})
            results.sort(key=lambda x: x['similarity'], reverse=True)
        except Exception as e:
            logger.error(f"Search failed: {e}")
        return results[:limit]

    def get_all(self) -> List[Dict[str, str]]:
        """Get all memories."""
        return [{'key': k, 'value': v} for k, v in self._memories.items()]

    def delete(self, key: str) -> bool:
        """Delete a memory."""
        if key in self._memories:
            del self._memories[key]
            del self._vectors[key]
            self._save()
            return True
        return False

    def clear(self):
        """Clear all memories."""
        self._memories = {}
        self._vectors = {}
        self._save()

    def _save(self):
        """Save memories to file."""
        try:
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(self._memories, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save: {e}")

    def _load(self):
        """Load memories from file."""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._memories = data
                    self._vectors = {}
                    for key, value in data.items():
                        try:
                            key_vec = self.hm.create_vector(key)
                            value_vec = self.hm.create_vector(value)
                            self._vectors[key] = (key_vec, value_vec)
                        except Exception:
                            pass  # Skip invalid entries
        except Exception as e:
            logger.error(f"Failed to load: {e}")
            self._memories = {}
            self._vectors = {}

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        return {
            'total_memories': len(self._memories),
            'vector_dim': self.hm.vector_dim,
            'storage_file': self.storage_path
        }


def get_hm_instance() -> HermesHolographicMemory:
    """Get or create singleton instance."""
    global _hm_instance
    if _hm_instance is None:
        _hm_instance = HermesHolographicMemory()
    return _hm_instance


def holographic_memory_tool(
    action: str,
    key: str = None,
    value: str = None,
    query: str = None,
    limit: int = 5,
    store: Optional[HermesHolographicMemory] = None,
) -> str:
    """Holographic memory tool entry point."""
    if store is None:
        store = get_hm_instance()

    if action == "add":
        if not key or not value:
            return json.dumps({"success": False, "error": "key and value are required for add"})
        success = store.add(key, value)
        return json.dumps({"success": success, "action": "add", "key": key, "value": value})

    elif action == "recall":
        if not key:
            return json.dumps({"success": False, "error": "key is required for recall"})
        result = store.recall(key)
        return json.dumps({"success": True, "action": "recall", "key": key, "value": result})

    elif action == "search":
        if not query:
            return json.dumps({"success": False, "error": "query is required for search"})
        results = store.search(query, limit=limit)
        return json.dumps({"success": True, "action": "search", "query": query, "results": results})

    elif action == "get_all":
        memories = store.get_all()
        return json.dumps({"success": True, "action": "get_all", "memories": memories})

    elif action == "delete":
        if not key:
            return json.dumps({"success": False, "error": "key is required for delete"})
        success = store.delete(key)
        return json.dumps({"success": success, "action": "delete", "key": key})

    elif action == "clear":
        store.clear()
        return json.dumps({"success": True, "action": "clear"})

    elif action == "stats":
        stats = store.get_stats()
        return json.dumps({"success": True, "action": "stats", "stats": stats})

    else:
        return json.dumps({"success": False, "error": f"Unknown action: {action}"})


def check_holographic_memory_requirements() -> bool:
    """Check if holographic_memory is available."""
    try:
        from holographic_memory import HolographicMemory
        return True
    except ImportError:
        return False


# OpenAI Function-Calling Schema
HOLOGRAPHIC_MEMORY_SCHEMA = {
    "name": "holographic_memory",
    "description": (
        "Holographic memory for storing and retrieving information using vector similarity. "
        "Uses HRR (Holographic Reduced Representations) for associative memory.\n\n"
        "Actions:\n"
        "- add: Add a key-value memory (key=identifier, value=content)\n"
        "- recall: Get exact value by key\n"
        "- search: Semantic search - finds memories similar to query\n"
        "- get_all: List all stored memories\n"
        "- delete: Delete a specific memory by key\n"
        "- clear: Delete ALL memories (use with caution)\n"
        "- stats: Get memory statistics\n\n"
        "Best for: Storing facts, preferences, and context that should persist across sessions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "recall", "search", "get_all", "delete", "clear", "stats"],
                "description": "The action to perform"
            },
            "key": {
                "type": "string",
                "description": "Memory key (for add, recall, delete)"
            },
            "value": {
                "type": "string",
                "description": "Memory value (for add)"
            },
            "query": {
                "type": "string",
                "description": "Search query (for search)"
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (for search, default: 5)"
            },
        },
        "required": ["action"],
    },
}


# Registry
from tools.registry import registry, tool_error

registry.register(
    name="holographic_memory",
    toolset="memory",
    schema=HOLOGRAPHIC_MEMORY_SCHEMA,
    handler=lambda args, **kw: holographic_memory_tool(
        action=args.get("action", ""),
        key=args.get("key"),
        value=args.get("value"),
        query=args.get("query"),
        limit=args.get("limit", 5),
        store=kw.get("store"),
    ),
    check_fn=check_holographic_memory_requirements,
    emoji="🔮",
)
