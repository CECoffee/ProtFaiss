"""
tests/test_gpu.py — GPU 管理模块单元测试

使用 unittest.mock 模拟 torch.cuda，可在无 GPU 环境下运行。
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGpuModule(unittest.TestCase):

    def _make_config(self, multi_gpu=True, faiss_devices="auto", encoding_device="auto"):
        return {
            "gpu": {
                "multi_gpu_enabled": multi_gpu,
                "encoding_device": encoding_device,
                "faiss_devices": faiss_devices,
                "faiss_temp_memory_mb": 1500,
                "memory_reserve_mb": 500,
            }
        }

    # ------------------------------------------------------------------
    # get_device_count
    # ------------------------------------------------------------------

    @patch("torch.cuda.is_available", return_value=True)
    @patch("torch.cuda.device_count", return_value=4)
    def test_get_device_count_with_gpus(self, mock_count, mock_avail):
        from app.core import gpu
        self.assertEqual(gpu.get_device_count(), 4)

    @patch("torch.cuda.is_available", return_value=False)
    def test_get_device_count_no_cuda(self, mock_avail):
        from app.core import gpu
        self.assertEqual(gpu.get_device_count(), 0)

    # ------------------------------------------------------------------
    # get_gpu_memory
    # ------------------------------------------------------------------

    @patch("torch.cuda.is_available", return_value=True)
    @patch("torch.cuda.device_count", return_value=2)
    @patch("torch.cuda.mem_get_info", return_value=(8 * 1024**3, 24 * 1024**3))
    def test_get_gpu_memory(self, mock_mem, mock_count, mock_avail):
        from app.core import gpu
        result = gpu.get_gpu_memory(0)
        self.assertEqual(result["total"], 24 * 1024)
        self.assertEqual(result["free"], 8 * 1024)
        self.assertEqual(result["used"], 16 * 1024)

    @patch("torch.cuda.is_available", return_value=False)
    def test_get_gpu_memory_no_cuda(self, mock_avail):
        from app.core import gpu
        result = gpu.get_gpu_memory(0)
        self.assertEqual(result, {"total": 0, "used": 0, "free": 0})

    # ------------------------------------------------------------------
    # get_available_devices — toggle off
    # ------------------------------------------------------------------

    @patch("torch.cuda.is_available", return_value=True)
    @patch("torch.cuda.device_count", return_value=4)
    def test_get_available_devices_toggle_off(self, mock_count, mock_avail):
        from app.core import gpu
        cfg = self._make_config(multi_gpu=False)
        with patch("app.core.config_loader.get_config", return_value=cfg):
            devices = gpu.get_available_devices()
        self.assertEqual(devices, [0])

    # ------------------------------------------------------------------
    # get_available_devices — toggle on, auto
    # ------------------------------------------------------------------

    @patch("torch.cuda.is_available", return_value=True)
    @patch("torch.cuda.device_count", return_value=3)
    def test_get_available_devices_toggle_on_auto(self, mock_count, mock_avail):
        from app.core import gpu
        cfg = self._make_config(multi_gpu=True, faiss_devices="auto")
        with patch("app.core.config_loader.get_config", return_value=cfg):
            devices = gpu.get_available_devices()
        self.assertEqual(devices, [0, 1, 2])

    # ------------------------------------------------------------------
    # get_available_devices — explicit list
    # ------------------------------------------------------------------

    @patch("torch.cuda.is_available", return_value=True)
    @patch("torch.cuda.device_count", return_value=4)
    def test_get_available_devices_explicit_list(self, mock_count, mock_avail):
        from app.core import gpu
        cfg = self._make_config(multi_gpu=True, faiss_devices=[0, 2])
        with patch("app.core.config_loader.get_config", return_value=cfg):
            devices = gpu.get_available_devices()
        self.assertEqual(devices, [0, 2])

    # ------------------------------------------------------------------
    # get_available_devices — no GPU
    # ------------------------------------------------------------------

    @patch("torch.cuda.is_available", return_value=False)
    def test_get_available_devices_no_gpu(self, mock_avail):
        from app.core import gpu
        cfg = self._make_config(multi_gpu=True)
        with patch("app.core.config_loader.get_config", return_value=cfg):
            devices = gpu.get_available_devices()
        self.assertEqual(devices, [])

    # ------------------------------------------------------------------
    # get_encoding_device — auto selects best GPU
    # ------------------------------------------------------------------

    @patch("torch.cuda.is_available", return_value=True)
    @patch("torch.cuda.device_count", return_value=2)
    def test_get_encoding_device_auto_selects_most_free(self, mock_count, mock_avail):
        import torch
        from app.core import gpu

        def mock_mem_info(device_id):
            # GPU 0: 4GB free, GPU 1: 16GB free
            return (4 * 1024**3, 24 * 1024**3) if device_id == 0 else (16 * 1024**3, 24 * 1024**3)

        cfg = self._make_config(encoding_device="auto")
        with patch("app.core.config_loader.get_config", return_value=cfg), \
             patch("torch.cuda.mem_get_info", side_effect=mock_mem_info):
            device = gpu.get_encoding_device()
        self.assertEqual(device, torch.device("cuda:1"))

    @patch("torch.cuda.is_available", return_value=False)
    def test_get_encoding_device_cpu_fallback(self, mock_avail):
        import torch
        from app.core import gpu
        cfg = self._make_config(encoding_device="auto")
        with patch("app.core.config_loader.get_config", return_value=cfg):
            device = gpu.get_encoding_device()
        self.assertEqual(device, torch.device("cpu"))

    @patch("torch.cuda.is_available", return_value=True)
    @patch("torch.cuda.device_count", return_value=2)
    def test_get_encoding_device_explicit(self, mock_count, mock_avail):
        import torch
        from app.core import gpu
        cfg = self._make_config(encoding_device="cuda:1")
        with patch("app.core.config_loader.get_config", return_value=cfg):
            device = gpu.get_encoding_device()
        self.assertEqual(device, torch.device("cuda:1"))

    def test_get_encoding_device_forced_cpu(self):
        import torch
        from app.core import gpu
        cfg = self._make_config(encoding_device="cpu")
        with patch("app.core.config_loader.get_config", return_value=cfg):
            device = gpu.get_encoding_device()
        self.assertEqual(device, torch.device("cpu"))


if __name__ == "__main__":
    unittest.main()
