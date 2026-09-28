"""验证流水线恢复状态的签名、产物核验和排他锁。"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.pipeline_state import PipelineState, pipeline_run_lock


def test_same_signature_resumes_and_missing_artifact_is_recomputed() -> None:
    """同签名可恢复，但完成标记不能掩盖丢失的产物。"""
    with TemporaryDirectory() as temporary_directory:
        cache_root = Path(temporary_directory) / ".pipeline_cache"
        artifact_path = cache_root / "factor.parquet"
        state = PipelineState.open(cache_root, {"config": {"run": True}}, False)
        artifact_path.write_bytes(b"result")
        state.mark_complete("factors", "alpha")

        resumed = PipelineState.open(
            cache_root,
            {"config": {"run": True}},
            False,
        )
        assert resumed.pending_items(
            "factors",
            ["alpha"],
            {"alpha": (artifact_path,)},
        ) == ()

        artifact_path.unlink()
        assert resumed.pending_items(
            "factors",
            ["alpha"],
            {"alpha": (artifact_path,)},
        ) == ("alpha",)


def test_signature_mismatch_preserves_cache_until_fresh_run() -> None:
    """签名变化必须拒绝混用；fresh 只重建流水线缓存。"""
    with TemporaryDirectory() as temporary_directory:
        cache_root = Path(temporary_directory) / ".pipeline_cache"
        stale_artifact = cache_root / "stale.parquet"
        PipelineState.open(cache_root, {"config": {"version": 1}}, False)
        stale_artifact.write_bytes(b"stale")

        with pytest.raises(RuntimeError, match="--fresh"):
            PipelineState.open(cache_root, {"config": {"version": 2}}, False)
        assert stale_artifact.read_bytes() == b"stale"

        PipelineState.open(cache_root, {"config": {"version": 2}}, True)
        assert not stale_artifact.exists()
        stored_state = json.loads(
            (cache_root / "run_state.json").read_text(encoding="utf-8")
        )
        assert stored_state["signature"]["config"]["version"] == 2


def test_output_root_lock_rejects_a_concurrent_run() -> None:
    """同一输出根同时只能有一个流水线持有排他锁。"""
    with TemporaryDirectory() as temporary_directory:
        output_root = Path(temporary_directory) / "output"
        with pipeline_run_lock(output_root):
            with pytest.raises(RuntimeError, match="已有流水线运行"):
                with pipeline_run_lock(output_root):
                    pass
