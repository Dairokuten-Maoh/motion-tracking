import unittest
from web_lookup import answer,query_from,public_link,sources_from,validate,SEARCH_LOCK
from conversation import BusyError

RESULTS=[{'title':'Example','href':'https://example.com/info','body':'An example fact.'}]

class WebLookupTests(unittest.TestCase):
    def test_explicit_routing(self):
        self.assertEqual(query_from('Search the web for Google Calendar API'),'Google Calendar API')
        self.assertEqual(query_from('Please look up Taipei 101 height'),'Taipei 101 height')
        self.assertIsNone(query_from('Show my calendar tomorrow'))
        self.assertIsNone(query_from('What did I say today?'))
    def test_empty_search_never_calls_provider(self):
        result=answer('Search the web for',lambda q:self.fail('Unexpected search'))
        self.assertTrue(result['insufficient_evidence'])
    def test_links_are_public_http_only(self):
        for url in ['javascript:alert(1)','file:///etc/passwd','http://127.0.0.1','http://10.0.0.1','http://localhost','https://user:pass@example.com','https://pc.tail123.ts.net']:
            self.assertFalse(public_link(url),url)
    def test_duplicate_and_empty_results_removed(self):
        self.assertEqual(len(sources_from(RESULTS*2+[{'href':'https://example.org','body':''}])),1)
    def test_only_query_sent_to_search(self):
        queries=[]
        def search(q):queries.append(q);return RESULTS
        result=answer('Look up sample',search,lambda q,s:{'answer':'An example fact.','source_ids':['1'],'insufficient_evidence':False})
        self.assertEqual(queries,['sample']);self.assertEqual(result['web_sources'][0]['url'],RESULTS[0]['href'])
    def test_hallucinated_source_rejected(self):
        result=answer('Look up sample',lambda q:RESULTS,lambda q,s:{'answer':'A fact.','source_ids':['999'],'insufficient_evidence':False})
        self.assertTrue(result['insufficient_evidence']);self.assertIn('could not produce',result['answer'])
    def test_no_results_skips_model(self):
        result=answer('Look up sample',lambda q:[],lambda *a:self.fail('Unexpected model'))
        self.assertIn('no usable',result['answer'])
    def test_provider_failure_clear(self):
        def fail(q):raise OSError('private diagnostic')
        result=answer('Look up sample',fail)
        self.assertNotIn('private diagnostic',str(result));self.assertTrue(result['insufficient_evidence'])
    def test_search_lock_released_after_failure(self):
        answer('Look up sample',lambda q:[])
        self.assertTrue(SEARCH_LOCK.acquire(blocking=False));SEARCH_LOCK.release()
    def test_unrequested_question_does_not_search(self):
        self.assertIsNone(answer('What happened today?',lambda q:self.fail('Unexpected search')))

if __name__=='__main__':unittest.main()
