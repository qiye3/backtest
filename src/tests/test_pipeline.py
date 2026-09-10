"""构造CSV/Parquet验证独立运行、并行隔离、标准因子和图形文件。"""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
import numpy as np
import pandas as pd
import yaml
from examples.make_demo import make_demo
from src.config import load_config
from src.pipeline import run_pipeline
from src.data.factor_input import read_panel,sources


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.base=yaml.safe_load(make_demo(cls.root,20).read_text())
        cls.base['run']['modules']=['group_return','simple_backtest','account_backtest','plotting']
        cls.base['factor_input'].update(source='external',ids=[],files=[{'id':'alpha','path':str(cls.root/'inputs/my_factor_a.csv')},{'id':'beta','path':str(cls.root/'inputs/my_factor_b.csv')}])
        cls.base['group_return'].update(start='2020-11-01',end='2020-12-31',future_return_days=[5,10])
        cls.base['group_return']['grouping']['quantile_edges']=[[.9,1],[.99,1]]
        for k in ['simple_backtest','account_backtest']:
            cls.base[k].update(start='2021-01-01',end='2021-02-12');cls.base[k]['rebalance']['intervals_weeks']=[1]
        cls.base['simple_backtest']['grouping']['quantile_edges']=[[0,.5],[.5,1]]
        cls.base['account_backtest']['grouping']['quantile_edges']=[[0,1]]
        cls.base['plots'].update(dpi=65,formats=['png'],missing_results='error')
        cls.base['metrics']['ic_horizons']=[5,10]

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def config(self,name,**updates):
        c=deepcopy(self.base);c['experiment']['name']=name
        c.update(updates);path=self.root/f'{name}.yaml';path.write_text(yaml.safe_dump(c,allow_unicode=True,sort_keys=False))
        return path,c

    def test_parallel_independent_groups_metrics_and_four_figures(self):
        path,c=self.config('parallel');run_pipeline(path);out=load_config(path).output_dir
        for factor in ['alpha','beta']:
            folder=out/factor;self.assertEqual(len(list((folder/'figures').glob('*.png'))),4)
            self.assertEqual(pd.read_csv(folder/'group_return/definitions.csv').quantile_lower.tolist(),[.9,.99])
            a=pd.read_csv(folder/'simple_backtest/metrics.csv');b=pd.read_csv(folder/'account_backtest/metrics.csv')
            self.assertEqual(len(a),2);self.assertEqual(len(b),1)
            self.assertIn('ic_mean_5d',b);self.assertEqual(b.ic_scope_5d.iloc[0],'full_universe')
            self.assertEqual(b.start_5d.iloc[0],'2020-11-01')
        # 绘图重跑完全不需要原始因子或行情路径。
        c['data']['root']='not_available';c['factor_input']['files']=[];path.write_text(yaml.safe_dump(c))
        run_pipeline(path,['plotting'])

    def test_process_results_match_sequential_and_no_eval_dependency(self):
        path,c=self.config('sequential');c['parallel']['enabled']=False;path.write_text(yaml.safe_dump(c))
        run_pipeline(path,['account_backtest']);out=load_config(path,['account_backtest']).output_dir
        expected=pd.read_csv(out/'alpha/account_backtest/metrics.csv')
        c['experiment']['name']='process';c['parallel']['enabled']=True;path.write_text(yaml.safe_dump(c))
        run_pipeline(path,['account_backtest']);out=load_config(path,['account_backtest']).output_dir
        actual=pd.read_csv(out/'alpha/account_backtest/metrics.csv');pd.testing.assert_frame_equal(expected,actual)
        self.assertFalse((out/'alpha/group_return').exists());self.assertNotIn('ic_mean_5d',actual)

    def test_external_parquet_and_cli_selects_only_group_return(self):
        csv=self.root/'inputs/my_factor_a.csv';parquet=self.root/'inputs/alpha.parquet'
        pd.read_csv(csv).to_parquet(parquet,index=False)
        pd.testing.assert_frame_equal(read_panel(csv),read_panel(parquet))
        path,c=self.config('parquet');c.pop('factors');c['factor_input']['files']=[{'id':'alpha','path':str(parquet)}]
        # 评估模块不需要基准指数、权重或模拟账户配置。
        c['data']['benchmark']='ABSENT';c['account_backtest']={'not_a_config':True};path.write_text(yaml.safe_dump(c))
        r=subprocess.run([sys.executable,'-m','src.cli','--config',str(path),'--modules','group_return'],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr);out=load_config(path,['group_return']).output_dir
        self.assertTrue((out/'alpha/group_return/ic.csv.gz').exists());self.assertFalse((out/'alpha/account_backtest').exists())

    def test_standard_factor_only_generates_all_twenty_variants(self):
        path,c=self.config('standard');repo=Path(__file__).resolve().parents[1]
        c['factors']['configs']=[str(p) for p in sorted((repo/'configs/factors').glob('*.yaml'))]
        c['factors'].update(start='2020-01-01',end='2021-02-12');c.pop('factor_input');path.write_text(yaml.safe_dump(c))
        run_pipeline(path,['factors']);manifest=json.loads((Path(c['factors']['values_dir'])/'manifest.json').read_text())
        self.assertEqual(len(manifest['entries']),20)
        out=load_config(path,['factors']).output_dir;self.assertFalse((out/'roe_level.smooth_1d').exists())
        # 下游只核对文件内容，不需要重新实例化其构造器。
        c.pop('factors');c['factor_input']={'source':'generated','values_dir':self.base['factors']['values_dir'],'ids':['roe_level.smooth_1d']};path.write_text(yaml.safe_dump(c))
        run_pipeline(path,['group_return']);self.assertTrue((out/'roe_level.smooth_1d/group_return/summary.csv').exists())

    def test_failed_factor_does_not_mask_success(self):
        invalid=self.root/'inputs/invalid.csv';invalid.write_text('date,S0\n2021-01-01,bad\n')
        path,c=self.config('mixed');c['factor_input']['files'][1]['path']=str(invalid);path.write_text(yaml.safe_dump(c))
        with self.assertRaises(RuntimeError):run_pipeline(path,['account_backtest'])
        out=load_config(path,['account_backtest']).output_dir;status=pd.read_csv(out/'run_status.csv').set_index('factor_id')
        self.assertEqual(status.loc['alpha','status'],'succeeded');self.assertEqual(status.loc['beta','status'],'failed')
        self.assertTrue((out/'beta/error.txt').exists())

    def test_config_examples_and_invalid_options(self):
        for p in Path('configs').glob('*.yaml'):load_config(p)
        path,c=self.config('invalid');c['simple_backtest']['horizon_days']=20;path.write_text(yaml.safe_dump(c))
        with self.assertRaisesRegex(ValueError,'unknown'):load_config(path,['simple_backtest'])
        c['simple_backtest'].pop('horizon_days');c['account_backtest']['grouping']['quantile_edges']=[.1,.2];path.write_text(yaml.safe_dump(c))
        with self.assertRaises(ValueError):load_config(path,['account_backtest'])


if __name__=='__main__':unittest.main()
