"""
Holographic Memory Wrapper for Hermes Agent
简化 holographic_memory 的使用流程
"""

import sys
import os
import sysconfig
sys.path.insert(0, os.path.join(sysconfig.get_paths()['purelib'], 'src'))

from holographic_memory import HolographicMemory
from typing import Optional, List, Dict, Any
import json
import os


class HermesHolographicMemory:
    """简化版的 Holographic Memory 封装"""
    
    def __init__(self, vector_size: int = 4096, seed: int = 42, storage_path: str = None):
        self.hm = HolographicMemory(vector_size=vector_size, seed=seed)
        self.storage_path = storage_path or os.path.expanduser("~/.hermes/holographic_memory.json")
        self._memories: Dict[str, str] = {}  # key -> value
        self._vectors: Dict[str, Any] = {}  # key -> (key_vec, value_vec)
        self._load()
    
    def add(self, key: str, value: str) -> bool:
        """添加一条记忆"""
        try:
            key_vec = self.hm.create_vector(key)
            value_vec = self.hm.create_vector(value)
            self._memories[key] = value
            self._vectors[key] = (key_vec, value_vec)
            self._save()
            return True
        except Exception as e:
            print(f"添加记忆失败: {e}")
            return False
    
    def recall(self, key: str) -> Optional[str]:
        """根据 key 精确回忆值"""
        return self._memories.get(key)
    
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """搜索记忆 - 基于向量相似度"""
        results = []
        query_vec = self.hm.create_vector(query)
        
        for key, value in self._memories.items():
            key_vec, value_vec = self._vectors[key]
            # 计算 query 与 key 和 value 的相似度
            sim_key = self.hm.similarity(query_vec, key_vec)
            sim_value = self.hm.similarity(query_vec, value_vec)
            sim = max(sim_key, sim_value)  # 取较高的
            results.append({'key': key, 'value': value, 'similarity': sim})
        
        # 按相似度排序
        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:limit]
    
    def get_all(self) -> List[Dict[str, str]]:
        """获取所有记忆"""
        return [{'key': k, 'value': v} for k, v in self._memories.items()]
    
    def delete(self, key: str) -> bool:
        """删除记忆"""
        if key in self._memories:
            del self._memories[key]
            del self._vectors[key]
            self._save()
            return True
        return False
    
    def clear(self):
        """清空所有记忆"""
        self._memories = {}
        self._vectors = {}
        self._save()
    
    def _save(self):
        """保存到文件"""
        try:
            with open(self.storage_path, 'w') as f:
                json.dump(self._memories, f, indent=2)
        except Exception as e:
            print(f"保存失败: {e}")
    
    def _load(self):
        """从文件加载"""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    self._memories = data
                    # 重建 vectors
                    self._vectors = {}
                    for key, value in data.items():
                        key_vec = self.hm.create_vector(key)
                        value_vec = self.hm.create_vector(value)
                        self._vectors[key] = (key_vec, value_vec)
        except Exception as e:
            print(f"加载失败: {e}")
            self._memories = {}
            self._vectors = {}
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'total_memories': len(self._memories),
            'vector_dim': self.hm.vector_dim,
            'storage_file': self.storage_path
        }


# 测试
if __name__ == "__main__":
    print("🧪 测试 Holographic Memory Wrapper")
    print("=" * 50)
    
    hm = HermesHolographicMemory(storage_path="/tmp/test_hm.json")
    hm.clear()
    
    # 添加记忆
    print("\n📝 添加记忆:")
    hm.add("user_name", "TUF GAMING")
    hm.add("system", "Windows WSL Ubuntu")
    hm.add("platforms", "Feishu and WeChat")
    hm.add("location", "F: drive")
    hm.add("note", "喜欢玩硬件改装")
    print("✅ 添加完成")
    
    # 精确读取
    print("\n🔍 精确读取:")
    print(f"user_name -> {hm.recall('user_name')}")
    print(f"system -> {hm.recall('system')}")
    print(f"platforms -> {hm.recall('platforms')}")
    
    # 模糊搜索
    print("\n🔎 模糊搜索 'platform':")
    results = hm.search("platform")
    for r in results:
        print(f"  {r['key']} -> {r['value']} (相似度: {r['similarity']:.3f})")
    
    print("\n🔎 模糊搜索 'windows':")
    results = hm.search("windows")
    for r in results:
        print(f"  {r['key']} -> {r['value']} (相似度: {r['similarity']:.3f})")
    
    # 所有记忆
    print("\n📋 所有记忆:")
    for m in hm.get_all():
        print(f"  {m['key']} -> {m['value']}")
    
    # 统计
    print("\n📊 统计:")
    print(hm.get_stats())
