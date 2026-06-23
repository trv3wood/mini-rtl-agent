from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch


def load_external_modules(external_root: Path):
    sys.path.insert(0, str(external_root))
    from src.common import (  # type: ignore[import-not-found]
        ensure_dir,
        format_rerank_prompt,
        get_device,
        get_reranker_template_tokens,
        load_reranker_model,
        tokenize_reranker_text,
    )
    from src.data_io import load_jsonl  # type: ignore[import-not-found]

    return {
        "ensure_dir": ensure_dir,
        "format_rerank_prompt": format_rerank_prompt,
        "get_device": get_device,
        "get_reranker_template_tokens": get_reranker_template_tokens,
        "load_reranker_model": load_reranker_model,
        "tokenize_reranker_text": tokenize_reranker_text,
        "load_jsonl": load_jsonl,
    }


def score_candidates_with_reranker(
    model,
    tokenizer,
    query_text: str,
    candidates: list[dict],
    prompt_format: str,
    max_length: int,
    batch_size: int,
    device,
    helpers: dict,
) -> list[float]:
    prefix_tokens, suffix_tokens = helpers["get_reranker_template_tokens"](tokenizer)
    token_true_id = tokenizer.convert_tokens_to_ids("yes")
    token_false_id = tokenizer.convert_tokens_to_ids("no")

    texts = [
        helpers["format_rerank_prompt"](
            candidate["name"],
            candidate.get("description", candidate.get("desc", "")),
            candidate["body"],
            query_text,
            prompt_format=prompt_format,
        )
        for candidate in candidates
    ]
    tokenized = [
        helpers["tokenize_reranker_text"](text, tokenizer, prefix_tokens, suffix_tokens, max_length)
        for text in texts
    ]

    scores: list[float] = []
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else 0
    for start in range(0, len(tokenized), batch_size):
        batch_ids = tokenized[start : start + batch_size]
        max_len = max(len(item) for item in batch_ids)
        padded, masks = [], []
        for ids in batch_ids:
            pad_len = max_len - len(ids)
            padded.append([pad_id] * pad_len + ids)
            masks.append([0] * pad_len + [1] * len(ids))
        input_ids = torch.tensor(padded, dtype=torch.long, device=device)
        attention_mask = torch.tensor(masks, dtype=torch.long, device=device)
        with torch.no_grad():
            logits = model(input_ids=input_ids, attention_mask=attention_mask).logits[:, -1, :]
            batch_scores = (logits[:, token_true_id] - logits[:, token_false_id]).float().cpu().tolist()
        scores.extend(batch_scores)
    return scores


def main() -> int:
    parser = argparse.ArgumentParser(description="Rerank a local mini-rtl-agent SkillRouter query.")
    parser.add_argument("--external-root", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--retrieval-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--reranker-model-or-path", default="pipizhao/SkillRouter-Reranker-0.6B")
    parser.add_argument("--tier", choices=("easy", "hard"), default="easy")
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--prompt-format", choices=("flat-full", "flat-nd", "struct"), default="flat-full")
    args = parser.parse_args()

    external_root = Path(args.external_root).resolve()
    data_root = Path(args.data_root).resolve()
    helpers = load_external_modules(external_root)
    tasks = helpers["load_jsonl"](data_root / "tasks.jsonl")
    pool = helpers["load_jsonl"](data_root / args.tier)
    pool_by_id = {str(item.get("skill_id") or item.get("id") or ""): item for item in pool}
    retrieval = json.loads(Path(args.retrieval_json).read_text(encoding="utf-8"))

    device = helpers["get_device"]()
    model, tokenizer = helpers["load_reranker_model"](args.reranker_model_or_path)
    model.to(device).eval()

    reranked: dict[str, list[str]] = {}
    for task in tasks:
        task_id = task["task_id"]
        retrieved_ids = [str(item) for item in retrieval.get(task_id, [])]
        candidates = [pool_by_id[skill_id] for skill_id in retrieved_ids if skill_id in pool_by_id]
        if not candidates:
            reranked[task_id] = []
            continue
        scores = score_candidates_with_reranker(
            model,
            tokenizer,
            task["instruction_text"],
            candidates,
            args.prompt_format,
            args.max_length,
            args.batch_size,
            device,
            helpers,
        )
        pairs = sorted(
            zip([str(item.get("skill_id") or item.get("id") or "") for item in candidates], scores),
            key=lambda item: item[1],
            reverse=True,
        )
        reranked[task_id] = [skill_id for skill_id, _ in pairs]

    output_path = Path(args.output_json)
    helpers["ensure_dir"](output_path.parent)
    output_path.write_text(json.dumps(reranked, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[saved] {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
