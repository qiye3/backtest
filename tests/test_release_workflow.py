"""验证正式五组入口、策略入口和 tmux 日志约定。"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import run_all_factor_backtests as factor_runner  # noqa: E402
import run_strategy_backtests as strategy_runner  # noqa: E402
from build_release_packages import _build_strategies  # noqa: E402
from tmux_runner import _logged_shell_command, launch_in_tmux  # noqa: E402


class ReleaseWorkflowTests(unittest.TestCase):
    """检查发布包暴露的正式运行语义。"""

    def test_five_factor_groups_use_overall_only_configuration(self) -> None:
        """五组模板都应关闭回测和单因子图，并开启两张总图。"""
        self.assertEqual(
            factor_runner.GROUPS,
            (
                "growth",
                "quality",
                "value",
                "first_batch",
                "second_batch",
            ),
        )
        for group_name in factor_runner.GROUPS:
            config_path = (
                PROJECT_ROOT
                / "factors"
                / f"{group_name}_factors"
                / "run_config.example.yaml"
            )
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            run_settings = config["run"]
            self.assertTrue(run_settings["factors"])
            self.assertTrue(run_settings["group_return"])
            self.assertTrue(run_settings["overall_evaluation"])
            self.assertEqual(
                config["factors"]["selected_variants"],
                ["raw"],
            )
            self.assertFalse(run_settings["simple_backtest"])
            self.assertFalse(run_settings["account_backtest"])
            self.assertFalse(run_settings["plotter"])
            self.assertTrue(
                config["plots"]["overall"]["factor_distribution_grid"][
                    "enabled"
                ]
            )
            self.assertTrue(
                config["plots"]["overall"]["group_return_grid"]["enabled"]
            )
            self.assertTrue(
                config["output"]["save_parquet"]["group_return"]
            )

    def test_factor_runner_overrides_templates_with_overall_only_mode(self) -> None:
        """一键入口应防止模板漂移重新打开因子回测或单因子图。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            arguments = SimpleNamespace(
                factors_root=PROJECT_ROOT / "factors",
                data_root=workspace / "data",
                output_root=workspace / "output",
            )

            configs = factor_runner._build_configs(arguments)

        experiment_variants = {
            f"{group_name}_{variant_name}": variant_name
            for group_name in factor_runner.GROUPS
            for variant_name in factor_runner.VARIANTS
        }
        self.assertEqual(tuple(configs), tuple(experiment_variants))
        for experiment_name, config in configs.items():
            self.assertFalse(config["run"]["simple_backtest"])
            self.assertFalse(config["run"]["account_backtest"])
            self.assertFalse(config["run"]["plotter"])
            self.assertTrue(config["run"]["overall_evaluation"])
            self.assertEqual(
                config["factors"]["selected_variants"],
                [experiment_variants[experiment_name]],
            )
            self.assertEqual(
                Path(config["output"]["root"]).name,
                experiment_name,
            )

    def test_strategy_runner_keeps_only_strategy_figures_enabled(self) -> None:
        """指数增强配置应运行 simple 回测且不绘制内部因子图。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            arguments = SimpleNamespace(
                data_root=workspace / "data",
                output_root=workspace / "output",
            )
            for suite_name in strategy_runner.STRATEGY_SUITES:
                _, config = strategy_runner._build_config(
                    suite_name,
                    PROJECT_ROOT,
                    arguments,
                )
                self.assertTrue(config["run"]["strategy_simple_backtest"])
                self.assertFalse(config["run"]["strategy_account_backtest"])
                self.assertTrue(config["run"]["plotter"])
                self.assertTrue(config["plots"]["strategy"]["enabled"])
                for plot_name in (
                    "distribution",
                    "evaluation",
                    "simple",
                    "account",
                ):
                    self.assertFalse(config["plots"][plot_name]["enabled"])

    def test_default_strategy_run_uses_combined_suite(self) -> None:
        """默认运行时成长100应与其他五个策略同级输出。"""
        self.assertEqual(
            strategy_runner._selected_suites("all"),
            ("roadshow",),
        )

    def test_strategy_package_contains_shared_factor_runtime(self) -> None:
        """Strategies 包应携带 roadshow 因子实现需要的最小公共模块。"""
        with TemporaryDirectory() as temporary_directory:
            staging_root = Path(temporary_directory) / "strategies_release"
            staging_root.mkdir()

            _build_strategies(staging_root)

            self.assertTrue((staging_root / "factors" / "__init__.py").is_file())
            self.assertTrue(
                (staging_root / "factors" / "fundamental_utils.py").is_file()
            )
            self.assertFalse((staging_root / "factors" / "config").exists())

    def test_tmux_command_retains_failed_log_and_deletes_successful_log(self) -> None:
        """后台命令应使用 pipefail，并按 Python 退出码决定日志去留。"""
        with TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory) / "output"
            with (
                patch("tmux_runner.shutil.which", return_value="/usr/bin/tmux"),
                patch("tmux_runner.subprocess.run") as run_mock,
                patch("tmux_runner.sys.argv", ["runner.py", "--flag"]),
            ):
                session_name = launch_in_tmux(output_root, "factor_backtest")

            tmux_command = run_mock.call_args.args[0]
            shell_command = tmux_command[-1]
            self.assertEqual(tmux_command[:4], ["/usr/bin/tmux", "new-session", "-d", "-s"])
            self.assertIn(session_name, tmux_command)
            self.assertIn("--foreground", shell_command)
            self.assertIn("PIPESTATUS[0]", shell_command)
            self.assertIn("tee", shell_command)
            self.assertIn("if [ \"$status\" -eq 0 ]; then rm -f", shell_command)

    def test_tmux_is_required_for_default_formal_run(self) -> None:
        """缺少 tmux 时不能静默退回前台执行。"""
        with TemporaryDirectory() as temporary_directory:
            with patch("tmux_runner.shutil.which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "需要 tmux"):
                    launch_in_tmux(Path(temporary_directory), "factor_backtest")

    def test_logged_shell_command_applies_log_retention_policy(self) -> None:
        """成功命令删除日志，失败命令保留日志并返回原退出码。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            success_log = workspace / "success.log"
            success_result = subprocess.run(
                [
                    "bash",
                    "-lc",
                    _logged_shell_command(
                        [sys.executable, "-c", "print('success')"],
                        success_log,
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(success_result.returncode, 0)
            self.assertFalse(success_log.exists())

            failure_log = workspace / "failure.log"
            failure_result = subprocess.run(
                [
                    "bash",
                    "-lc",
                    _logged_shell_command(
                        [
                            sys.executable,
                            "-c",
                            "import sys; print('failure'); sys.exit(7)",
                        ],
                        failure_log,
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(failure_result.returncode, 7)
            self.assertEqual(failure_log.read_text().strip(), "failure")


if __name__ == "__main__":
    unittest.main()
