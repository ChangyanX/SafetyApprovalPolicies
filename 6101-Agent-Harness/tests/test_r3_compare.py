import unittest
from src.r3_compare import compare


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.row=dict(episode_id='e1',suite='banking',policy='hybrid_stub',k='1',condition='attacked',
                      user_task_id='user_task_1',attack='direct',injection_task_id='injection_task_0',repeat='0')
        self.result=dict(self.row,status='ok',utility=True,security=False,review_count=1,executed_calls=[])
    def test_attack_direction_and_error_bounds(self):
        rows=[self.row,dict(self.row,episode_id='e2'),dict(self.row,episode_id='e3')]
        error=dict(self.result,episode_id='e2',status='error',error='timeout',utility=False,security=False)
        out=compare(rows,[self.result,error])['groups'][0]
        self.assertEqual(out['valid_only_rate'],1)
        self.assertEqual(out['planned_lower_bound'],1/3)
        self.assertEqual(out['planned_upper_bound'],1)
        self.assertEqual((out['errors'],out['missing']),(1,1))
        self.result['security']=True
        self.assertEqual(compare([self.row],[self.result])['groups'][0]['valid_only_rate'],0)
    def test_clean_sentinel_not_attack(self):
        self.row['condition']='clean';self.result.update(condition='clean',security=True)
        out=compare([self.row],[self.result])['groups'][0]
        self.assertEqual(out['valid_only_rate'],1)
        self.assertIsNone(out['attack_success_valid_only'])
    def test_duplicates_mismatch_budget_and_audit_rejected(self):
        for change in [dict(episode_id='unknown'),dict(policy='full_approve'),dict(review_count=2),
                       dict(utility='true'),dict(executed_calls=[{}])]:
            with self.subTest(change=change),self.assertRaises(ValueError):compare([self.row],[dict(self.result,**change)])
        with self.assertRaises(ValueError):compare([self.row],[self.result,self.result])
        with self.assertRaises(ValueError):compare([self.row,self.row],[])
    def test_empty_results_not_false_zero_performance(self):
        out=compare([self.row],[])['groups'][0]
        self.assertIsNone(out['valid_only_rate']);self.assertEqual(out['planned_upper_bound'],1)

if __name__=='__main__':unittest.main()
