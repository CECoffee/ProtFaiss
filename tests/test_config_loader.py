"""
tests/test_config_loader.py — config_loader 单元测试

测试 mtime 缓存、热重载、默认值 fallback。
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfigLoader(unittest.TestCase):

    def setUp(self):
        # Reset module-level cache before each test
        import app.core.config_loader as cl
        cl._cached_config = None
        cl._cached_mtime = -1.0

    def _write_yml(self, path: str, content: str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # ------------------------------------------------------------------
    # Basic load
    # ------------------------------------------------------------------

    def test_loads_valid_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("gpu:\n  multi_gpu_enabled: false\nsearch:\n  faiss_search_workers: 4\n")
            tmp = f.name
        try:
            import app.core.config_loader as cl
            import app.core.config as cfg
            orig = cfg.CONFIG_YML_PATH
            cfg.CONFIG_YML_PATH = tmp
            cl._cached_config = None
            cl._cached_mtime = -1.0
            result = cl.get_config()
            self.assertFalse(result["gpu"]["multi_gpu_enabled"])
            self.assertEqual(result["search"]["faiss_search_workers"], 4)
            # Defaults merged in for missing keys
            self.assertIn("threadpool_workers", result["search"])
        finally:
            cfg.CONFIG_YML_PATH = orig
            os.unlink(tmp)

    # ------------------------------------------------------------------
    # Fallback to defaults when file missing
    # ------------------------------------------------------------------

    def test_fallback_when_file_missing(self):
        import app.core.config_loader as cl
        import app.core.config as cfg
        orig = cfg.CONFIG_YML_PATH
        cfg.CONFIG_YML_PATH = "/nonexistent/path/config.yml"
        cl._cached_config = None
        cl._cached_mtime = -1.0
        try:
            result = cl.get_config()
            self.assertIn("gpu", result)
            self.assertIn("search", result)
            self.assertIn("build", result)
            self.assertTrue(result["gpu"]["multi_gpu_enabled"])  # default is True
        finally:
            cfg.CONFIG_YML_PATH = orig

    # ------------------------------------------------------------------
    # Fallback on invalid YAML
    # ------------------------------------------------------------------

    def test_fallback_on_invalid_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("this: is: not: valid: yaml: [\n")
            tmp = f.name
        try:
            import app.core.config_loader as cl
            import app.core.config as cfg
            orig = cfg.CONFIG_YML_PATH
            cfg.CONFIG_YML_PATH = tmp
            cl._cached_config = None
            cl._cached_mtime = -1.0
            result = cl.get_config()
            self.assertIn("gpu", result)
        finally:
            cfg.CONFIG_YML_PATH = orig
            os.unlink(tmp)

    # ------------------------------------------------------------------
    # Mtime-based hot reload
    # ------------------------------------------------------------------

    def test_hot_reload_on_mtime_change(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("search:\n  faiss_search_workers: 8\n")
            tmp = f.name
        try:
            import app.core.config_loader as cl
            import app.core.config as cfg
            orig = cfg.CONFIG_YML_PATH
            cfg.CONFIG_YML_PATH = tmp
            cl._cached_config = None
            cl._cached_mtime = -1.0

            result1 = cl.get_config()
            self.assertEqual(result1["search"]["faiss_search_workers"], 8)

            # Modify file and bump mtime
            time.sleep(0.01)
            self._write_yml(tmp, "search:\n  faiss_search_workers: 16\n")
            # Touch to ensure mtime changes
            os.utime(tmp, None)

            result2 = cl.get_config()
            self.assertEqual(result2["search"]["faiss_search_workers"], 16)
        finally:
            cfg.CONFIG_YML_PATH = orig
            os.unlink(tmp)

    # ------------------------------------------------------------------
    # force_reload
    # ------------------------------------------------------------------

    def test_force_reload(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("search:\n  faiss_search_workers: 8\n")
            tmp = f.name
        try:
            import app.core.config_loader as cl
            import app.core.config as cfg
            orig = cfg.CONFIG_YML_PATH
            cfg.CONFIG_YML_PATH = tmp
            cl._cached_config = None
            cl._cached_mtime = -1.0

            cl.get_config()
            self._write_yml(tmp, "search:\n  faiss_search_workers: 32\n")
            result = cl.force_reload()
            self.assertEqual(result["search"]["faiss_search_workers"], 32)
        finally:
            cfg.CONFIG_YML_PATH = orig
            os.unlink(tmp)

    # ------------------------------------------------------------------
    # get() helper
    # ------------------------------------------------------------------

    def test_get_helper(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("build:\n  encoding_batch_size: 64\n")
            tmp = f.name
        try:
            import app.core.config_loader as cl
            import app.core.config as cfg
            orig = cfg.CONFIG_YML_PATH
            cfg.CONFIG_YML_PATH = tmp
            cl._cached_config = None
            cl._cached_mtime = -1.0
            self.assertEqual(cl.get("build", "encoding_batch_size"), 64)
            self.assertEqual(cl.get("build", "nonexistent_key", "default_val"), "default_val")
        finally:
            cfg.CONFIG_YML_PATH = orig
            os.unlink(tmp)

    # ------------------------------------------------------------------
    # Deep merge: override partial section, keep defaults for rest
    # ------------------------------------------------------------------

    def test_deep_merge_keeps_defaults(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("search:\n  faiss_search_workers: 4\n")
            tmp = f.name
        try:
            import app.core.config_loader as cl
            import app.core.config as cfg
            orig = cfg.CONFIG_YML_PATH
            cfg.CONFIG_YML_PATH = tmp
            cl._cached_config = None
            cl._cached_mtime = -1.0
            result = cl.get_config()
            # Overridden
            self.assertEqual(result["search"]["faiss_search_workers"], 4)
            # Default preserved
            self.assertEqual(result["search"]["threadpool_workers"], 32)
        finally:
            cfg.CONFIG_YML_PATH = orig
            os.unlink(tmp)

    # ------------------------------------------------------------------
    # Returns deep copy (mutations don't affect cache)
    # ------------------------------------------------------------------

    def test_returns_deep_copy(self):
        import app.core.config_loader as cl
        import app.core.config as cfg
        orig = cfg.CONFIG_YML_PATH
        cfg.CONFIG_YML_PATH = "/nonexistent/path/config.yml"
        cl._cached_config = None
        cl._cached_mtime = -1.0
        try:
            result1 = cl.get_config()
            result1["gpu"]["multi_gpu_enabled"] = "mutated"
            result2 = cl.get_config()
            self.assertNotEqual(result2["gpu"]["multi_gpu_enabled"], "mutated")
        finally:
            cfg.CONFIG_YML_PATH = orig


if __name__ == "__main__":
    unittest.main()
