"""No OR-Tools required. Contract smoke tests for unified data/ship + D3/D5.

Run from repo root: python3 -m unittest discover -s integration_tests -v
The CP-SAT/full-dashboard tests are separate and need ortools/flask installed.
"""
import unittest
from pathlib import Path
from governor import loader
from governor.integration import crosscheck_admission
from governor.rightofway import right_of_way


class IntegrationBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=loader.load_raw()

    def test_physical_model_is_source_of_ship_limits(self):
        r=self.raw
        self.assertEqual(r['ship']['power']['reserve_kw']['slow'],200)
        self.assertEqual(r['ship']['power']['degraded_reserve_kw']['slow'],100)
        self.assertEqual(r['ship']['power']['reserve_kw']['cruise'],200)
        self.assertEqual(r['ship']['data']['backbone_mbps'],20000)
        self.assertEqual(r['ship']['compute']['allocatable_fraction'],0.8)

    def test_guests_loaded_from_single_canonical_directory(self):
        r=self.raw
        self.assertIn('G1',r['card']);self.assertIn('G5',r['card'])
        self.assertIn('physical ship_specs authority','|'.join(r['source_notes']))
        for gid, card in r['card'].items():
            self.assertEqual(card['id'],gid)
            self.assertEqual(loader.validate_manifest(card,r['schema']),[],gid)

    def test_synthetic_g3_power_is_synchronized(self):
        guests=loader.load_guest_data(self.raw)
        self.assertAlmostEqual(guests['G3'].modes['full']['kw'],1.0)
        self.assertAlmostEqual(guests['G5'].modes['low']['kw'],8)
        self.assertAlmostEqual(guests['G5'].modes['full']['kw'],45)

    def test_independent_physical_check_never_certifies_admission(self):
        plan={'installed':{'G1':True},'config':{'G1':'mast'},
              'mode_n':{'G1':'full'},'lines':{'mast':'port'}}
        out=crosscheck_admission({'plan':plan},self.raw,{'state':{'crew':14,'location':'port'}})
        self.assertEqual(out['status'],'PASS')
        self.assertEqual(out['assessment_status'],'UNKNOWN')
        self.assertEqual(out['full_admission_status'],'NOT_EVALUATED')
        self.assertNotIn('certified',out)

    def test_unmappable_mode_is_not_silently_zeroed(self):
        plan={'installed':{'G1':True},'config':{'G1':'mast'},
              'mode_n':{'G1':'off'},'lines':{'mast':'port'}}
        out=crosscheck_admission({'plan':plan},self.raw,{})
        self.assertEqual(out['status'],'UNKNOWN')

    def test_scenario_b_priority_changes_decision(self):
        scn=loader.load_scenario(Path('scenarios/B_right_of_way.yaml'))
        rescue=right_of_way(self.raw,scn,'rescue')
        survey=right_of_way(self.raw,scn,'survey')
        self.assertNotEqual(rescue['decision'],survey['decision'])
        self.assertTrue(rescue['within_2s'])
        self.assertTrue(survey['within_2s'])

    def test_d5_crew_rule_has_distinct_confirmation(self):
        scn=loader.load_scenario(Path('scenarios/B_right_of_way.yaml'))
        c0=right_of_way(self.raw,scn,'rescue',crew=0)
        c14=right_of_way(self.raw,scn,'rescue',crew=14)
        self.assertIn('no crew',c0['confirmation'])
        self.assertNotEqual(c0['confirmation'],c14['confirmation'])

    def test_g6_optional_but_safety_critical_when_present(self):
        if 'G6' not in self.raw['card']:
            self.skipTest('G6 is only in the newer live GitHub repository')
        g=loader.load_guest_data(self.raw)['G6']
        self.assertTrue(g.safety_critical)
        self.assertNotIn('off',g.modes)
        self.assertEqual(g.modes['full']['kw'],8.0)

if __name__=='__main__':unittest.main()
