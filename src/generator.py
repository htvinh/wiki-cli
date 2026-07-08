"""
generator.py

Produces a synthetic corpus of raw, unstructured text files.
Deterministic: same seed always produces the same corpus.
"""

import logging
import os
import random

from exceptions import RewriteError

logger = logging.getLogger(__name__)

TOPIC_POOL = [
    "Gradient Descent", "Attention Mechanism", "Tokenization", "Embedding Layer",
    "Transformer Block", "Backpropagation", "Batch Normalization", "Dropout",
    "Learning Rate Schedule", "Cross Entropy Loss", "Positional Encoding",
    "Layer Normalization", "Residual Connection", "Self Attention", "KV Cache",
    "Beam Search", "Greedy Decoding", "Top-K Sampling", "Temperature Scaling",
    "Fine Tuning", "LoRA Adapter", "Quantization", "Pruning", "Distillation",
    "Vector Index", "Cosine Similarity", "Hybrid Search", "Reranking",
    "Chunking Strategy", "Context Window", "Rate Limiting", "Circuit Breaker",
    "Retry Policy", "Prompt Template", "Few Shot Example", "Chain of Thought",
    "Tool Calling", "Function Schema", "Streaming Response", "Token Budget",
    "Semantic Cache", "Query Router", "Cost Tracking", "Latency Budget",
    "Model Registry", "Rollback Mechanism", "Integrity Hash", "Deployment Gate",
    "Canary Release", "Shadow Traffic",
]

RELATION_TEMPLATES = [
    "{a} is often paired with {b} in production pipelines.",
    "When debugging {a}, engineers frequently trace the issue back to {b}.",
    "{a} builds directly on the ideas behind {b}.",
    "A common mistake is tuning {a} without first checking {b}.",
    "{a} and {b} interact whenever the pipeline scales past a single node.",
    "Most implementations of {a} assume {b} is already configured correctly.",
]

FILLER_SENTENCES = [
    "This note was captured during a debugging session and may be incomplete.",
    "Revisit this after the next benchmark run.",
    "See related experiments in the archive folder for context.",
    "Numbers here are approximate and were not re-verified.",
    "This section needs a cleaner example before it is considered final.",
]


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def generate_corpus(output_dir: str, num_files: int, seed: int = 42) -> list:
    rng = random.Random(seed)
    os.makedirs(output_dir, exist_ok=True)

    all_topics = []
    for i in range(num_files):
        base_topic = TOPIC_POOL[i % len(TOPIC_POOL)]
        suffix = i // len(TOPIC_POOL)
        topic = base_topic if suffix == 0 else f"{base_topic} v{suffix + 1}"
        all_topics.append(topic)

    written = []
    for topic in all_topics:
        slug = _slugify(topic)

        others = [t for t in all_topics if t != topic]
        k = min(rng.randint(1, 3), len(others)) if others else 0
        related = rng.sample(others, k=k) if k else []

        lines = []
        if rng.random() < 0.5:
            lines.append(f"# {topic}")
        else:
            lines.append(topic.upper())

        if rng.random() < 0.7:
            lines.append(f"created: 2026-0{rng.randint(1,6)}-{rng.randint(10,28)}")
        if rng.random() < 0.4:
            lines.append(f"aliases: {slug}, {slug}_notes")

        lines.append("")
        for rel in related:
            template = rng.choice(RELATION_TEMPLATES)
            lines.append(template.format(a=topic, b=rel))
        lines.append("")
        lines.append(rng.choice(FILLER_SENTENCES))

        content = "\n".join(lines) + "\n"
        path = os.path.join(output_dir, f"{slug}.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            raise RewriteError(f"Cannot write {path}: {e}") from e
        written.append(path)

    logger.info("Generated %d files in %s (seed=%d)", num_files, output_dir, seed)
    return written


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    paths = generate_corpus("raw_notes", num_files=20, seed=42)
    print(f"Wrote {len(paths)} raw files to raw_notes/")
