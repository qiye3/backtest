"""命令行入口：使用配置run.modules，或用--modules/单个模块名显式选择。"""
import argparse
from src.pipeline import run_pipeline


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module',nargs='?',default=None,help='factors/group_return/simple_backtest/account_backtest/plotting/all')
    parser.add_argument('--config',required=True,help='实验YAML路径')
    parser.add_argument('--modules',nargs='+',help='可选择多个模块，用空格或逗号分隔')
    args=parser.parse_args()
    if args.module and args.modules:parser.error('choose positional module or --modules')
    modules=[m for part in args.modules for m in part.split(',')] if args.modules else [args.module] if args.module else None
    run_pipeline(args.config,modules)


if __name__=='__main__':main()
