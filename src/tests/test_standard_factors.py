import unittest
import tempfile
from pathlib import Path
from copy import deepcopy
import numpy as np
import pandas as pd
import yaml
from src.data.fundamentals import normalize_financial, events_to_pit
from src.factors.growth import financial_panel
from src.factors.builder import validate_definition, build_panels, save_panels, load_panels
from src.factors.operators import smooth


class FinancialTests(unittest.TestCase):
    def test_revision_updates_current_comparison_without_overwriting_current_level(self):
        raw=pd.DataFrame({'S_INFO_WINDCODE':['A']*3,'ANN_DT':[20200430,20210430,20200430],
                          'ACTUAL_ANN_DT':[20200430,20210430,20210510],
                          'REPORT_PERIOD':[20200331,20210331,20200331],'S_QFA_ROE':[10.,20.,15.]})
        events=normalize_financial(raw,['S_QFA_ROE'])
        days=pd.to_datetime(['2021-04-29','2021-04-30','2021-05-10'])
        level=financial_panel(events,'S_QFA_ROE','level',days,['A'])
        yoy=financial_panel(events,'S_QFA_ROE','yoy_difference',days,['A'])
        np.testing.assert_allclose(level.A,[10,20,20])
        np.testing.assert_allclose(yoy.A.iloc[1:],[10,5])

    def test_same_day_batch_and_missing_lag_invalidate_previous_value(self):
        raw=pd.DataFrame({'S_INFO_WINDCODE':['A']*4,'ANN_DT':[20200430,20210430,20210430,20210801],
             'REPORT_PERIOD':[20200331,20210331,20200331,20210630],'S_QFA_ROE':[10,20,12,30]})
        days=pd.to_datetime(['2021-04-30','2021-08-02'])
        results=[]
        for x in [raw,raw.iloc[::-1]]:
            results.append(financial_panel(normalize_financial(x,['S_QFA_ROE']),'S_QFA_ROE','yoy_difference',days,['A']))
        pd.testing.assert_frame_equal(*results)
        self.assertEqual(results[0].iloc[0,0],8)
        self.assertTrue(pd.isna(results[0].iloc[1,0]))

    def test_conflicting_same_day_versions_are_rejected(self):
        x=pd.DataFrame({'S_INFO_WINDCODE':['A','A'],'ANN_DT':[20200430]*2,'REPORT_PERIOD':[20200331]*2,'x':[1,2]})
        with self.assertRaises(ValueError): normalize_financial(x,['x'])
        x['version']=[1,2]
        result=financial_panel(normalize_financial(x,['x']),'x','level',pd.to_datetime(['2020-04-30']),['A'])
        self.assertEqual(result.iloc[0,0],2)

    def test_other_stock_event_dates_do_not_change_quarter_lag(self):
        raw=pd.DataFrame({'S_INFO_WINDCODE':['A','A','B','B'],'ANN_DT':[20200430,20200801,20200504,20200518],
             'REPORT_PERIOD':[20200331,20200630,20200331,20200331],'x':[10,15,99,100]})
        days=pd.bdate_range('2020-04-30','2020-08-03')
        combined=financial_panel(normalize_financial(raw,['x']),'x','qoq_difference',days,['A','B'])
        alone=financial_panel(normalize_financial(raw.iloc[:2],['x']),'x','qoq_difference',days,['A'])
        pd.testing.assert_series_equal(combined.A,alone.A)
        self.assertEqual(alone.iloc[-1,0],5)


    def test_current_year_forecast_is_reset_at_year_boundary(self):
        from src.data.consensus import reset_forecast_year, consensus_panel
        raw=pd.DataFrame({'date':pd.to_datetime(['2019-12-31','2020-01-03']), 'code':['A','A'], 'x':[8.,9.]})
        reset=reset_forecast_year(raw,['x'],'2020-01-03')
        values=consensus_panel(reset,pd.to_datetime(['2019-12-31','2020-01-02','2020-01-03']),['A'],'x')
        self.assertEqual(values.iloc[0,0],8.)
        self.assertTrue(pd.isna(values.iloc[1,0]))
        self.assertEqual(values.iloc[2,0],9.)


class FactorTests(unittest.TestCase):
    def definition(self):
        return yaml.safe_load(Path('configs/factors/roe_yoy_diff.yaml').read_text())

    def test_variant_cannot_change_operator_or_input(self):
        for override in [{'method':'median'},{'params':{'method':'qoq_difference'}},{'windows':{'value_field':'x'}}]:
            d=self.definition(); d['variants'][0].update(override)
            with self.assertRaises(ValueError): validate_definition(d)

    def test_weekly_four_values_are_not_twenty_daily_values(self):
        days=pd.bdate_range('2020-01-01','2020-02-28')
        panel=pd.DataFrame({'A':np.arange(len(days),dtype=float)**2},index=days)
        d={'smoothing':{'method':'mean','unit':'weekly_closes'}}
        weekly=smooth(panel,d,{'smooth_window':4},days[-1])
        self.assertAlmostEqual(weekly.iloc[-1,0],panel.loc[['2020-02-07','2020-02-14','2020-02-21','2020-02-28'],'A'].mean())
        daily=smooth(panel,{'smoothing':{'method':'mean','unit':'trading_days'}},{'smooth_window':20},days[-1])
        self.assertNotAlmostEqual(weekly.iloc[-1,0],daily.iloc[-1,0])

    def test_artifact_detects_config_changes_and_tampering(self):
        d=self.definition(); days=pd.bdate_range('2020-01-01','2020-01-10')
        panels={f"{d['name']}.{v['name']}":pd.DataFrame({'A':np.arange(len(days),dtype=float)},index=days) for v in d['variants']}
        with tempfile.TemporaryDirectory() as tmp:
            save_panels(tmp,panels,[d],{'start':str(days[0]),'end':str(days[-1]),'universe_indices':['I']})
            loaded,_=load_panels(tmp,[d]); self.assertEqual(len(loaded),2)
            changed=deepcopy(d); changed['smoothing']['method']='median'
            with self.assertRaises(ValueError): load_panels(tmp,[changed])
            path=Path(tmp)/f'{next(iter(panels))}.csv.gz'; path.write_bytes(b'changed')
            with self.assertRaises(ValueError): load_panels(tmp,[d])

