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
        if torch.cuda.is_available():
            ESM2_MODEL.cuda()
    return ESM2_TOKENIZER, ESM2_MODEL

def clean_sequence(sequence: str) -> str:
    """去掉 FASTA header 和空白并转大写"""
    cleaned = re.sub(r"^>.*\n", "", sequence, flags=re.MULTILINE)
    cleaned = re.sub(r"\s", "", cleaned).upper()
    return cleaned

def blocking_encode(sequence_str: str, pooling: str = "mean"):
    """阻塞式编码：返回一个 torch.Tensor (B=1, dim)"""
    if ESM2_TOKENIZER is None or ESM2_MODEL is None:
        raise RuntimeError("ESM2 model not initialized. Call init_model() first.")
    inputs = ESM2_TOKENIZER(sequence_str, return_tensors="pt", max_length=2048, truncation=True)
    with torch.no_grad():
        input_ids = inputs["input_ids"]
        attention_mask = inputs["attention_mask"]
        if torch.cuda.is_available():
            input_ids = input_ids.cuda()
            attention_mask = attention_mask.cuda()
        outputs = ESM2_MODEL(input_ids=input_ids, attention_mask=attention_mask)
        features = outputs.last_hidden_state  # (B, L, C)
        masked_features = features * attention_mask.unsqueeze(2)  # mask padding
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
