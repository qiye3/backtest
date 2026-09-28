"""验证上层脚本只为明确选择的基础因子生成分域实验。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import yaml

from scripts.run_domain_research import _materialize_factor_runs
from src.config import save_config_snapshot
from src.factors.domains import DomainDefinition, DomainResearchConfig


def _factor_config(name: str) -> dict:
    return {
        "name": name,
        "implementation": {
            "module": "src.factors.ExampleFactor",
            "class": "ExampleFactor",
        },
        "params": {"lookback_days": 1},
        "postprocess": {"cross_section": {"method": "rank"}},
        "variants": [
            {
                "suffix": "raw",
                "neutralization": {"method": "none"},
            },
            {
                "suffix": "industry_neutral",
                "neutralization": {
                    "method": "industry_demean",
                    "source": "industry_history",
                    "field": "ind_class_code",
                },
            },
        ],
    }


def _domain_config(path: Path) -> DomainResearchConfig:
    return DomainResearchConfig(
        path=path,
        factor_names=("factor_a",),
        domains=(
            DomainDefinition(
                name="csi800",
                rule={
                    "type": "index_membership",
                    "index_code": "000906.SH",
                },
            ),
        ),
    )


def test_materialized_runs_only_include_selected_factor_and_raw_variant() -> None:
    """未列入 factor_names 的配置不应产生运行目录或域输出任务。"""
    with TemporaryDirectory() as temporary_directory:
        workspace = Path(temporary_directory)
        factor_directory = workspace / "factor_configs"
        factor_directory.mkdir()
        for factor_name in ("factor_a", "factor_b"):
            (factor_directory / f"{factor_name}.yaml").write_text(
                yaml.safe_dump(_factor_config(factor_name), sort_keys=False),
                encoding="utf-8",
            )

        base_config = SimpleNamespace(
            path=workspace / "base.yaml",
            output_root=workspace / "outputs",
            factor_config_directory=factor_directory,
            factor_domains=_domain_config(workspace / "domains.yaml"),
            external_return_path=None,
            raw={
                "run": {},
                "strategy_analysis": {"enabled": False},
                "factors": {"config_directory": str(factor_directory)},
                "output": {"root": "outputs"},
                "market_data": {
                    "source_root": "raw_data",
                    "cache_root": "market_cache",
                },
                "group_return": {"future_return_weeks": [4]},
                "plots": {
                    "overall": {
                        "factor_distribution_grid": {"enabled": False},
                        "group_return_grid": {"enabled": False},
                    }
                },
            },
        )

        run_paths = _materialize_factor_runs(base_config)

        assert len(run_paths) == 1
        generated_run = yaml.safe_load(run_paths[0].read_text(encoding="utf-8"))
        generated_factor_path = next(
            (run_paths[0].parent / "factors").glob("*.yaml")
        )
        generated_factor = yaml.safe_load(
            generated_factor_path.read_text(encoding="utf-8")
        )
        assert run_paths[0].parent.name == "factor_a"
        assert generated_factor["name"] == "factor_a"
        assert [variant["suffix"] for variant in generated_factor["variants"]] == [
            "raw",
            "industry_neutral",
        ]
        assert generated_run["factors"]["selected_variants"] == ["raw"]
        assert generated_run["output"]["root"].endswith("/outputs/factor_a")
        assert generated_run["plots"]["overall"]["group_return_grid"]["enabled"]


def test_config_snapshot_contains_replayable_domain_reference() -> None:
    """主配置快照应引用一同保存的规范化 domains YAML。"""
    with TemporaryDirectory() as temporary_directory:
        output_root = Path(temporary_directory)
        run_config = SimpleNamespace(
            output_root=output_root,
            raw={
                "factors": {
                    "config_directory": "/factor/configs",
                    "domain_config": "/research/domains.yaml",
                }
            },
            factor_domains=_domain_config(Path("/research/domains.yaml")),
            factor_parquet_files=None,
        )

        snapshot_path = save_config_snapshot(run_config)

        snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))
        domain_snapshot_path = output_root / "domain_config_snapshot.yaml"
        domain_snapshot = yaml.safe_load(
            domain_snapshot_path.read_text(encoding="utf-8")
        )
        assert snapshot["factors"]["domain_config"] == "domain_config_snapshot.yaml"
        assert domain_snapshot["factor_names"] == ["factor_a"]
        assert domain_snapshot["domains"][0]["name"] == "csi800"
