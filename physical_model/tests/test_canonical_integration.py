"""Cross-brain acceptance tests using unmodified canonical G1–G5 manifests."""
import copy
import json
from pathlib import Path
import unittest
from physical_model.manifest_adapter import (ROOT, load_canonical_guests, load_json,
    normalize_guests, evaluate_canonical)
from physical_model.resource_models import evaluate_all
from physical_model.resource_models.common import InputError

class CanonicalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.spec=load_json(ROOT/'physical_model/data/ship_specs.json')
        self.state=load_json(ROOT/'physical_model/data/example_state.json')
        self.runtime=load_json(ROOT/'physical_model/data/sample_runtime.json')
        self.profile=load_json(ROOT/'physical_model/data/resource_profiles.json')
        self.canonical=load_canonical_guests()
    def select(self,*ids):
        for gid, choice in self.runtime['guests'].items():
            choice['installed'] = gid in ids
    def inspect(self):
        
        for k,v in self.runtime.items():
            if k not in ('guests','notes'):
                self.state.setdefault(k,copy.deepcopy(v))
        guests,assumptions=normalize_guests(self.canonical,self.runtime|self.state,self.profile)
        return evaluate_all(self.spec,self.state,guests),guests,assumptions
    def test_schema_all_five(self):
        self.assertEqual({g['id'] for g in self.canonical},{'G1','G2','G3','G4','G5'})
    def test_original_manifests_unmodified(self):
        old=copy.deepcopy(self.canonical)
        self.inspect()
        self.assertEqual(self.canonical,old)
    def test_baseline_separates_timing(self):
        r,gs,_=self.inspect()
        self.assertEqual(r['status'],'PASS')
        self.assertFalse(r['timing_verified'])
        self.assertEqual({g['id'] for g in gs},{'G3','G4','G5'})
    def test_g5_mass_includes_separate_antenna(self):
        r,gs,_=self.inspect()
        self.assertEqual(next(g for g in gs if g['id']=='G5')['mass_kg'],3025)
        self.assertEqual(r['resources']['mass']['details']['demand_kg'],9565)
    def test_silence_g1_passive_allowed_and_no_satcom_demand(self):
        self.select('G1')
        self.state['emission']='silent'
        r,gs,_=self.inspect()
        self.assertEqual(r['status'],'PASS',r['resources']['datalinks']['reason'])
        self.assertEqual(r['resources']['datalinks']['details']['demand_mbps']['satcom'],0)
    def test_silence_g2_buffered_no_satcom(self):
        self.select('G2')
        self.state['emission']='silent'
        r,gs,_=self.inspect()
        self.assertEqual(r['resources']['datalinks']['status'],'PASS')
    def test_silence_g5_excluded(self):
        self.select('G5')
        self.state['emission']='silent'
        r,_,_=self.inspect()
        self.assertIn('G5.silence_exclusion',r['resources']['operational']['binding_constraints'])
    def test_g4_recovery_differs_from_charging(self):
        self.select('G4')
        self.runtime['guests']['G4']['operation']='launch_recovery'
        self.state.update(active_operations=['flight'],speed_kn=6,guest_state={'G4':{'battery_percent':60}})
        r,gs,_=self.inspect()
        self.assertEqual(gs[0]['modes']['standby']['power_kw'],2)
        self.assertEqual(r['resources']['operational']['status'],'PASS')
        self.runtime['guests']['G4']['power_mode']='charging_initial'
        self.state['guest_state']['G4']['mode_elapsed_minutes']=10
        r,gs,_=self.inspect()
        self.assertEqual(gs[0]['modes']['charging_initial']['power_kw'],35)
    def test_g4_no_recovery_below_5_kn(self):
        self.select('G4')
        self.runtime['guests']['G4']['operation']='launch_recovery'
        self.state['active_operations']=['flight']
        r,_,_=self.inspect()
        self.assertIn('G4.navigation.speed_knots.gte',r['resources']['operational']['binding_constraints'])
    def test_g4_deadline_if_battery_low(self):
        self.select('G4')
        self.runtime['guests']['G4']['operation']='launch_recovery'
        self.state.update(speed_kn=6,active_operations=['flight'],guest_state={'G4':{'battery_percent':18,'eta_to_landing_min':13,'minutes_since_low_battery':0}})
        r,_,_=self.inspect()
        self.assertIn('G4.emergency_recovery_eta',r['resources']['operational']['binding_constraints'])
        self.state['guest_state']['G4']['eta_to_landing_min']=10
        r,_,_=self.inspect()
        self.assertNotIn('G4.emergency_recovery_eta',r['resources']['operational']['binding_constraints'])
    def test_g3_survey_and_g4_recovery_incompatible(self):
        self.select('G3','G4')
        self.runtime['guests']['G3']['operation']='surveying'
        self.runtime['guests']['G4']['operation']='launch_recovery'
        self.state.update(speed_kn=3,active_operations=['flight'])
        r,_,_=self.inspect()
        self.assertEqual(r['resources']['operational']['status'],'FAIL')
    def test_g2_winch_requires_activity_and_duration(self):
        self.select('G2')
        self.runtime['guests']['G2']['power_mode']='winch_operation'
        r,_,_=self.inspect()
        self.assertIn('G2.winch_mode_activity',r['resources']['operational']['binding_constraints'])
        self.runtime['guests']['G2']['operation']='winch_operation'
        self.state.update(deck_machinery=True,guest_state={'G2':{'mode_elapsed_minutes':6}})
        r,_,_=self.inspect()
        self.assertIn('G2.sustained_duration',r['resources']['operational']['binding_constraints'])
    def test_g3_noninterruptible_charge(self):
        self.select('G3')
        self.state['mode_change_requests']=[{'guest_id':'G3','from_mode':'charging','to_mode':'standby','elapsed_minutes':40}]
        r,_,_=self.inspect()
        self.assertIn('G3.noninterruptible_charge',r['resources']['operational']['binding_constraints'])
    def test_g4_charge_over_twenty_minutes(self):
        self.select('G4')
        self.runtime['guests']['G4']['power_mode']='charging_initial'
        self.state['guest_state']={'G4':{'battery_percent':60,'mode_elapsed_minutes':21}}
        r,_,_=self.inspect()
        self.assertIn('G4.sustained_duration',r['resources']['operational']['binding_constraints'])
    def test_g5_roof_requires_available_roof_and_clearance(self):
        self.select('G5')
        self.runtime['guests']['G5']['placement']='bay2_hangar_roof'
        r,_,_=self.inspect()
        self.assertEqual(r['resources']['operational']['status'], 'PASS')
        self.state['hangar_roof_available']=False
        r,_,_=self.inspect()
        self.assertIn('G5.placement.platform.hangar_roof_available.eq',r['resources']['operational']['binding_constraints'])
        self.state['hangar_roof_available']=True
        self.select('G4','G5')
        self.state['drone_clearance_verified']=False
        r,_,_=self.inspect()
        self.assertIn('G5.placement.platform.drone_clearance_verified.eq',r['resources']['operational']['binding_constraints'])
    def test_degraded_cooling(self):
        self.state.update(seawater_c=30,cooling_fault=True)
        r,_,_=self.inspect()
        self.assertEqual(r['resources']['cooling']['details']['capacity_kw'],72)
    def test_generator_failure_105kw(self):
        self.state['gensets_online']=1
        self.runtime['guests']['G3']['power_mode']='charging'
        self.runtime['guests']['G4']['power_mode']='charging_initial'
        self.state['guest_state']={'G4':{'mode_elapsed_minutes':5}}
        r,_,_=self.inspect()
        self.assertEqual(r['resources']['electrical']['details']['demand_kw'],105)
        self.assertEqual(r['resources']['electrical']['status'],'FAIL')
        self.runtime['guests']['G5']['power_mode']='low_power'
        r,_,_=self.inspect()
        self.assertEqual(r['resources']['electrical']['details']['demand_kw'],68)
        self.assertEqual(r['resources']['electrical']['status'],'PASS')
    def test_crew_at_sea_installation(self):
        self.select('G4')
        self.state['install_requests']=[{'guest_id':'G4','change':'drone_swap','available_minutes':30}]
        self.state.update(speed_kn=6,sea_state=2,wind_kn=16)
        self.state['crew']=0
        r,_,_=self.inspect()
        self.assertIn('installation.crew',r['resources']['operational']['binding_constraints'])
        self.state['crew']=6
        r,_,_=self.inspect()
        self.assertEqual(r['resources']['operational']['status'],'PASS')
    def test_no_port_only_bay_install_at_sea(self):
        self.state['install_requests']=[{'guest_id':'G2','change':'bay_install'}]
        r,_,_=self.inspect()
        self.assertIn('installation.at_sea_physical_type',r['resources']['operational']['binding_constraints'])
    def test_zero_crew_already_clear_possible(self):
        self.select('G4')
        self.runtime['guests']['G4']['operation']='launch_recovery'
        self.state.update(crew=0,deck_state='clear',active_operations=['flight'],speed_kn=6)
        r,_,_=self.inspect()
        self.assertEqual(r['resources']['operational']['status'],'PASS')
    def test_radar_reduces_g1_capability(self):
        self.select('G1')
        self.state['own_radar_transmitting_nearby']=True
        r,_,_=self.inspect()
        self.assertEqual(r['resources']['operational']['details']['capability_modifiers']['G1']['remaining_capability_fraction'],.7)
    def test_never_mutate_canonical(self):
        r1,_,_=self.inspect()
        r2,_,_=self.inspect()
        self.assertEqual(r1,r2)
    def test_missing_assumption_not_zero(self):
        self.select('G4')
        del self.profile['guest_resource_profiles']['G4']['compute_by_mode']['standby']
        with self.assertRaises(InputError):
            self.inspect()

if __name__=='__main__':unittest.main()

class ThreeBrainTests(unittest.TestCase):
    def test_compose_state(self):
        from physical_model.brain_state import compose_state
        from physical_model.manifest_adapter import load_json, ROOT
        src=ROOT/'data/three_brains'
        vals={name:load_json(src/(name+'.json')) for name in
              ('navigation','platform','mission','environment','crew_context','timing')}
        combined=compose_state(**vals)
        self.assertEqual(combined['speed_kn'],3)
        self.assertEqual(combined['gensets_online'],2)
        self.assertEqual(combined['guest_state']['G4']['battery_percent'],60)
    def test_conflicting_owners_rejected(self):
        from physical_model.brain_state import compose_state
        with self.assertRaises(InputError):
            compose_state({'speed_kn':3},{'speed_kn':8},{})
