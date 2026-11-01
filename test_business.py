import unittest,tempfile,json,sys,struct
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from types import SimpleNamespace
from core import Store,DEFAULT,order_quote,data_dir,validate
from catalog import paper_size,configured_printers
import customers,office
from test_rendering import sample_profile
from windows_driver import job_blob

class BusinessTests(unittest.TestCase):
    def test_customer_search_and_excel_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            a=Store(Path(d)/'a');record=customers.upsert(a.db,{'name':'张三','community':'星河小区','building':'12栋','room':'1201','phone':'013800000001','qq':'001234','wechat':'wx_zhang','note':'=literal','alias':'老张'})
            for query in ['张三','zhangsan','zs','013800','001234','wx_zhang','老张','1201']:self.assertEqual(customers.search(a.db,query)[0]['id'],record['id'])
            file=Path(d)/'客户.xlsx';customers.export_xlsx(a.db,file);b=Store(Path(d)/'b');self.assertEqual(customers.import_xlsx(b.db,file),1);loaded=customers.get(b.db,record['id']);self.assertEqual(loaded['phone'],'013800000001');self.assertEqual(loaded['qq'],'001234');self.assertEqual(loaded['note'],'=literal');customers.import_xlsx(b.db,file);self.assertEqual(len(customers.search(b.db)),1);a.db.close();b.db.close()
    def test_import_failure_is_atomic(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);wb=Workbook();ws=wb.active;ws.append(['姓名','手机号']);ws.append(['第一条','123']);ws.append(['第二条','=1+1']);path=Path(d)/'bad.xlsx';wb.save(path);wb.close()
            with self.assertRaises(ValueError):customers.import_xlsx(store.db,path)
            self.assertEqual(customers.search(store.db),[]);store.db.close()
    def test_order_snapshot_survives_customer_delete(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);r=customers.upsert(store.db,{'name':'测试客户'});oid=store.order({'customer':r['name'],'customer_id':r['id']});store.db.execute('DELETE FROM customers');store.db.commit();self.assertEqual(json.loads(store.history()[0][3])['customer'],'测试客户');store.db.close()
    def test_binding_price_separate_from_pages(self):
        c=deepcopy(DEFAULT);c['bindings']=[{'name':'胶装','price':'5.00'}];item={'selected':list(range(10)),'options':{'paper':'A4','color':'黑白','duplex':'单面','copies':1}};q=order_quote(c,[item],'胶装',2);self.assertEqual(q['print_total'],'2.00');self.assertEqual(q['binding_total'],'10.00');self.assertEqual(q['total'],'12.00');c['billing']=False;self.assertEqual(order_quote(c,[item],'胶装',2)['total'],'0.00')
    def test_custom_paper_dimensions_and_native_fields(self):
        c=deepcopy(DEFAULT);c['papers']['自定义凭证']=[90,55];c['printers']=[{'name':'TEST','dpi':[600],'rules':[{'paper':'自定义凭证','color':'黑白','duplex':'单面'}]}];validate(c);options={'paper':'自定义凭证','paper_mm':[90,55],'duplex':'单面','color':'黑白'};blob=job_blob(sample_profile(),options);self.assertEqual(struct.unpack_from('<hhh',blob,78),(256,550,900));self.assertEqual(paper_size('6寸相纸',config=c),(101.6,152.4))
    def test_only_enabled_configured_printers(self):
        c=deepcopy(DEFAULT);c['printers']=[{'name':'A'},{'name':'B','enabled':False}];self.assertEqual(configured_printers(c),['A'])
    def test_portable_data_stays_next_to_executable(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'MoXu.exe';(Path(d)/'portable.flag').write_text('portable')
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',str(exe)):self.assertEqual(data_dir(),Path(d)/'data')
    def test_word_priority_and_no_silent_fallback_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'document.docx';source.write_bytes(b'test');output=Path(d)/'converted.pdf'
            def success(*args,**kwargs):output.write_bytes(b'%PDF-test');return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
            with patch('office.subprocess.run',side_effect=success),patch('office.libreoffice_path') as lo:self.assertEqual(office.convert(source,d,output),'Microsoft Word');lo.assert_not_called()
            output.unlink()
            with patch('office.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout=b'',stderr=b'failed')),patch('office.libreoffice_path') as lo:
                with self.assertRaises(RuntimeError):office.convert(source,d,output)
                lo.assert_not_called()
    def test_missing_word_falls_back_only_under_preferred_policy(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'document.docx';source.write_bytes(b'test');output=Path(d)/'converted.pdf';calls=[]
            def run(args,**kwargs):
                calls.append(args[0])
                if args[0]=='powershell.exe':return SimpleNamespace(returncode=15,stdout=b'NP_ENGINE_MISSING',stderr=b'')
                (Path(d)/'document.pdf').write_bytes(b'%PDF-test');return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
            with patch('office.subprocess.run',side_effect=run),patch('office.libreoffice_path',return_value='soffice-test'):self.assertIn('LibreOffice',office.convert(source,d,output));self.assertEqual(calls,['powershell.exe','soffice-test'])
            with patch('office.subprocess.run',side_effect=run),patch('office.libreoffice_path') as lo:
                with self.assertRaises(RuntimeError):office.convert(source,d,output,'仅 Microsoft Office')
                lo.assert_not_called()

if __name__=='__main__':unittest.main()
