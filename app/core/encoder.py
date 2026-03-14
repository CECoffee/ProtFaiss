from typing import Tuple
import re
import torch
from transformers import AutoTokenizer, EsmModel

from .config import ESM2_MODEL_DIR

# module-level handles (initialized in main.startup)
ESM2_TOKENIZER = None
ESM2_MODEL = None


def init_model(model_dir: str = None):
    global ESM2_TOKENIZER, ESM2_MODEL
    model_dir = model_dir or ESM2_MODEL_DIR
    if ESM2_TOKENIZER is None or ESM2_MODEL is None:
        ESM2_TOKENIZER = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        ESM2_MODEL = EsmModel.from_pretrained(model_dir, local_files_only=True)
        from app.core.gpu import get_encoding_device
        device = get_encoding_device()
        ESM2_MODEL.to(device)
        print(f"[encoder] ESM2 model loaded on {device}")
    return ESM2_TOKENIZER, ESM2_MODEL


def clean_sequence(sequence: str) -> str:
    """去掉 FASTA header 和空白并转大写"""
    cleaned = re.sub(r"^>.*\n", "", sequence, flags=re.MULTILINE)
    cleaned = re.sub(r"\s", "", cleaned).upper()
    return cleaned


def _safe_forward(input_ids, attention_mask, max_length: int, max_retries: int = 3):
    """
    带 OOM 重试的前向传播。
    OOM 时截断序列长度减半，最多重试 max_retries 次。
    最终仍 OOM 则 fallback 到 CPU。
    """
    device = next(ESM2_MODEL.parameters()).device
    current_max = max_length

    for attempt in range(max_retries + 1):
        try:
            ids = input_ids.to(device)
            mask = attention_mask.to(device)
            # 截断到当前允许的最大长度
            if ids.shape[1] > current_max:
                ids = ids[:, :current_max]
                mask = mask[:, :current_max]
            with torch.no_grad():
                outputs = ESM2_MODEL(input_ids=ids, attention_mask=mask)
            return outputs, mask
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            if attempt < max_retries:
                current_max = max(1, current_max // 2)
                print(
                    f"[encoder] OOM on attempt {attempt + 1}, "
                    f"retrying with max_length={current_max}"
                )
            else:
                # 最终 fallback 到 CPU
                print("[encoder] OOM persists after retries, falling back to CPU.")
                ESM2_MODEL.cpu()
                torch.cuda.empty_cache()
                ids = input_ids.cpu()[:, :current_max]
                mask = attention_mask.cpu()[:, :current_max]
                with torch.no_grad():
                    outputs = ESM2_MODEL(input_ids=ids, attention_mask=mask)
                return outputs, mask


def blocking_encode(sequence_str: str, pooling: str = "mean"):
    """阻塞式编码：返回一个 torch.Tensor (B=1, dim)，带 OOM 重试保护。"""
    if ESM2_TOKENIZER is None or ESM2_MODEL is None:
        raise RuntimeError("ESM2 model not initialized. Call init_model() first.")
    inputs = ESM2_TOKENIZER(sequence_str, return_tensors="pt", max_length=2048, truncation=True)
    outputs, attention_mask = _safe_forward(
        inputs["input_ids"], inputs["attention_mask"], max_length=2048
    )
    features = outputs.last_hidden_state  # (B, L, C)
    masked_features = features * attention_mask.unsqueeze(2)
    sum_features = torch.sum(masked_features, dim=1)
    if pooling == 'mean':
        pooled = sum_features / attention_mask.sum(dim=1, keepdim=True)
    elif pooling == 'max':
        pooled, _ = torch.max(masked_features, dim=1)
    elif pooling == 'sum':
        pooled = sum_features
    else:
        pooled = sum_features / attention_mask.sum(dim=1, keepdim=True)
    return pooled.detach().contiguous()  # shape (B, C)
