import unittest, tempfile, json
from copy import deepcopy
from pathlib import Path
from core import DEFAULT, pages, quote, route, Store, validate,migrate_config,active_quality
from remote_contract import normalize_request

class Tests(unittest.TestCase):
    def item(self,n=3,copies=1,duplex='双面长边'):
        return {'selected':list(range(n)),'options':{'paper':'A4','color':'黑白','duplex':duplex,'dpi':600,'copies':copies,'printer':'自动分配'}}
    def test_ranges(self):
        self.assertEqual(pages('1-3,2,5',5),[0,1,2,4])
        for s in ['0','6','3-2','1-2-3','1,']:
            with self.assertRaises(ValueError):pages(s,5)
    def test_progressive_order_aggregation(self):
        self.assertEqual(quote(DEFAULT,[self.item(12),self.item(13)])['total'],'4.75')
    def test_odd_duplex_per_copy_and_file(self):
        c=deepcopy(DEFAULT);c['prices'][1]['unit']='张'
        self.assertEqual(quote(c,[self.item(3,2),self.item(1)])['groups'][0]['quantity'],5)
    def test_double_price_by_sheet(self):
        c=deepcopy(DEFAULT);c['prices'][1].update(unit='张',tiers=[[None,'0.30']])
        self.assertEqual(quote(c,[self.item(3)])['total'],'0.60')
    def test_volume_boundaries(self):
        c=deepcopy(DEFAULT);c['prices'][1].update(mode='volume',tiers=[[1,'0.20'],[20,'0.15'],[100,'0.10']])
        for count,total in [(19,'3.80'),(20,'3.00'),(21,'3.15'),(100,'10.00')]:self.assertEqual(quote(c,[self.item(count)])['total'],total)
    def test_categories_never_pool_tiers(self):
        c=deepcopy(DEFAULT)
        for r in c['prices']:r.update(mode='volume',tiers=[[1,'0.20'],[20,'0.10']])
        items=[]
        for paper,color,duplex in [('A4','黑白','单面'),('A4','黑白','双面长边'),('A4','彩色','单面'),('A3','黑白','单面')]:
            i=self.item(10,duplex=duplex);i['options'].update(paper=paper,color=color);items.append(i)
        self.assertEqual(quote(c,items)['total'],'8.00');self.assertEqual(len(quote(c,items)['groups']),4)
    def test_long_short_edges_share_double_category(self):
        c=deepcopy(DEFAULT);c['prices'][1].update(mode='volume',tiers=[[1,'0.20'],[5,'0.10']])
        self.assertEqual(quote(c,[self.item(3),self.item(3,duplex='双面短边')])['total'],'0.60')
    def test_legacy_conflict_requires_review(self):
        c=deepcopy(DEFAULT);c.pop('schema_version');c['prices']=[{'paper':'A4','color':'黑白','duplex':d,'unit':'面','tiers':[[None,p]]} for d,p in [('双面长边','0.20'),('双面短边','0.30')]]
        migrated=migrate_config(c);self.assertTrue(migrated['billing_review_required']);self.assertEqual(migrated['prices'][0]['duplex'],'双面')
        with self.assertRaises(ValueError):quote(migrated,[self.item()])
    def test_migration_splits_wildcard(self):
        c=deepcopy(DEFAULT);c.pop('schema_version');c['prices']=[dict(c['prices'][0],duplex='*')];m=migrate_config(c)
        self.assertEqual([r['duplex'] for r in m['prices']],['单面','双面'])
    def test_price_precision(self):
        c=deepcopy(DEFAULT);c['prices'][0]['tiers']=[[None,'0.123']]
        with self.assertRaises(ValueError):validate(c)
    def test_missing_price_blocks(self):
        i=self.item();i['options']['paper']='B5'
        with self.assertRaises(ValueError):quote(DEFAULT,[i])
    def test_routing_checks_manual_capabilities(self):
        c=deepcopy(DEFAULT);c['printers']=[{'name':'HP','dpi':[600],'priority':1,'rules':[{'paper':'A4','color':'黑白','duplex':'双面长边'}]}]
        o=self.item()['options'];self.assertEqual(route(c,o,['HP']),'HP')
        o['color']='彩色';o['printer']='HP'
        with self.assertRaises(ValueError):route(c,o,['HP'])
    def test_quality_switch_controls_dpi_routing(self):
        c=deepcopy(DEFAULT);c['printers']=[{'name':'HP','dpi':[600],'rules':[{'paper':'A4','color':'黑白','duplex':'双面长边'}],'quality_profiles':[{'name':'标准'},{'name':'高'}],'active_quality':'高'}]
        o=self.item()['options'];o['dpi']=1200
        with self.assertRaises(ValueError):route(c,o,['HP'])
        self.assertIsNone(active_quality(c,'HP'));c['native_quality_enabled']=True
        self.assertEqual(route(c,o,['HP']),'HP');self.assertEqual(active_quality(c,'HP')['name'],'高')
    def test_invalid_price(self):
        for tiers in [[[20,'1'],[10,'1'],[None,'1']],[[None,'NaN']],[[None,'-1']],[[10,'1']]]:
            c=deepcopy(DEFAULT);c['prices'][0]['tiers']=tiers
            with self.assertRaises(ValueError):validate(c)
    def test_store_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d);oid=s.order({'test':True});s.status(oid,'正在提交');s.db.close();s=Store(d)
            self.assertIn('中断',s.history()[0][2]);s.db.close()
    def test_remote_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):normalize_request({'version':'v1','idempotency_key':'12345678','files':[{'upload_id':'../outside.pdf'}]},d)
    def test_legacy_settings_and_orders_survive(self):
        with tempfile.TemporaryDirectory() as d:
            legacy=deepcopy(DEFAULT);legacy.pop('presets',None);legacy['communities']={'原有小区':['8栋']};legacy['prices'][0]['tiers']=[[None,'0.33']]
            Path(d,'settings.json').write_text(json.dumps(legacy),'utf-8')
            s=Store(d);oid=s.order({'customer':'existing'});s.db.close();s=Store(d)
            self.assertEqual(s.config['communities'],legacy['communities']);self.assertEqual([r['tiers'] for r in s.config['prices']],[r['tiers'] for r in legacy['prices']]);self.assertEqual(s.config['presets'],[]);self.assertEqual(s.history()[0][0],oid);s.db.close()
    def test_presets_reject_duplicate_names(self):
        c=deepcopy(DEFAULT);p={'name':'常用','options':dict(self.item()['options'],fit='完整留白',landscape=False)};c['presets']=[p,deepcopy(p)]
        with self.assertRaises(ValueError):validate(c)

if __name__=='__main__':unittest.main()
