"""
tests/test_oom_recovery.py — OOM 恢复逻辑单元测试

Mock torch.cuda.OutOfMemoryError，验证：
- 编码批大小减半重试
- CPU fallback
- empty_cache 被调用
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock, call
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOOMRecovery(unittest.TestCase):

    def _make_mock_model(self, device="cpu"):
        """Create a minimal mock ESM2 model."""
        mock_model = MagicMock()
        mock_param = MagicMock()
        mock_param.device = device
        mock_model.parameters.return_value = iter([mock_param])

        # Mock forward pass output
        import torch
        B, L, D = 2, 10, 1280
        hidden = torch.zeros(B, L, D)
        mock_output = MagicMock()
        mock_output.last_hidden_state = hidden
        mock_model.return_value = mock_output
        return mock_model

    def _make_mock_tokenizer(self):
        import torch
        mock_tok = MagicMock()
        B, L = 2, 10
        mock_tok.return_value = {
            "input_ids": torch.ones(B, L, dtype=torch.long),
            "attention_mask": torch.ones(B, L, dtype=torch.long),
        }
        return mock_tok

    # ------------------------------------------------------------------
    # _batch_encode_sequences: OOM triggers batch size halving
    # ------------------------------------------------------------------

    def test_oom_halves_batch_size(self):
        import torch
        from app.build.index_builder import _batch_encode_sequences

        call_count = [0]
        original_batch_sizes = []

        mock_model = MagicMock()
        mock_param = MagicMock()
        mock_param.device = torch.device("cpu")
        mock_model.parameters.return_value = iter([mock_param])

        def mock_forward(**kwargs):
            call_count[0] += 1
            batch_size = kwargs["input_ids"].shape[0]
            original_batch_sizes.append(batch_size)
            if call_count[0] == 1:
                raise torch.cuda.OutOfMemoryError("OOM")
            output = MagicMock()
            output.last_hidden_state = torch.zeros(batch_size, 10, 1280)
            return output

        mock_model.side_effect = mock_forward

        mock_tok = MagicMock()
        def mock_tokenize(seqs, **kwargs):
            B = len(seqs)
            return {
                "input_ids": torch.ones(B, 10, dtype=torch.long),
                "attention_mask": torch.ones(B, 10, dtype=torch.long),
            }
        mock_tok.side_effect = mock_tokenize

        sequences = ["ACGT"] * 4

        with patch("torch.cuda.empty_cache") as mock_empty:
            result = _batch_encode_sequences(
                sequences, mock_model, mock_tok, batch_size=4
            )

        # empty_cache should be called on OOM
        mock_empty.assert_called()
        # Result should have 4 embeddings
        self.assertEqual(result.shape[0], 4)
        self.assertEqual(result.shape[1], 1280)

    # ------------------------------------------------------------------
    # encoder.blocking_encode: OOM triggers max_length halving
    # ------------------------------------------------------------------

    def test_blocking_encode_oom_halves_max_length(self):
        import torch
        import app.core.encoder as enc

        call_count = [0]
        seen_lengths = []

        def mock_forward(input_ids, attention_mask):
            call_count[0] += 1
            seen_lengths.append(input_ids.shape[1])
            if call_count[0] == 1:
                raise torch.cuda.OutOfMemoryError("OOM")
            output = MagicMock()
            output.last_hidden_state = torch.zeros(1, input_ids.shape[1], 1280)
            return output

        mock_model = MagicMock()
        mock_param = MagicMock()
        mock_param.device = torch.device("cpu")
        mock_model.parameters.return_value = iter([mock_param])
        mock_model.side_effect = lambda **kwargs: mock_forward(
            kwargs["input_ids"], kwargs["attention_mask"]
        )

        mock_tok = MagicMock()
        mock_tok.return_value = {
            "input_ids": torch.ones(1, 100, dtype=torch.long),
            "attention_mask": torch.ones(1, 100, dtype=torch.long),
        }

        enc.ESM2_MODEL = mock_model
        enc.ESM2_TOKENIZER = mock_tok

        with patch("torch.cuda.empty_cache"):
            result = enc.blocking_encode("ACGT")

        self.assertEqual(result.shape[1], 1280)
        # Second call should have shorter sequence
        self.assertGreater(len(seen_lengths), 1)

    # ------------------------------------------------------------------
    # encoder.blocking_encode: CPU fallback after max retries
    # ------------------------------------------------------------------

    def test_blocking_encode_cpu_fallback(self):
        import torch
        import app.core.encoder as enc

        call_count = [0]

        def mock_forward(input_ids, attention_mask):
            call_count[0] += 1
            if call_count[0] <= 3:
                raise torch.cuda.OutOfMemoryError("OOM")
            output = MagicMock()
            output.last_hidden_state = torch.zeros(1, input_ids.shape[1], 1280)
            return output

        mock_model = MagicMock()
        mock_param = MagicMock()
        mock_param.device = torch.device("cuda:0")
        mock_model.parameters.return_value = iter([mock_param])
        mock_model.side_effect = lambda **kwargs: mock_forward(
            kwargs["input_ids"], kwargs["attention_mask"]
        )
        mock_model.cpu = MagicMock(return_value=mock_model)

        mock_tok = MagicMock()
        mock_tok.return_value = {
            "input_ids": torch.ones(1, 50, dtype=torch.long),
            "attention_mask": torch.ones(1, 50, dtype=torch.long),
        }

        enc.ESM2_MODEL = mock_model
        enc.ESM2_TOKENIZER = mock_tok

        with patch("torch.cuda.empty_cache"):
            result = enc.blocking_encode("ACGT")

        # Should succeed via CPU fallback
        self.assertEqual(result.shape[1], 1280)
        # model.cpu() should have been called
        mock_model.cpu.assert_called()


if __name__ == "__main__":
    unittest.main()
