"""Independent boundary, invalid-input and degraded-state checks."""
import copy
import json
import math
from pathlib import Path
import unittest
from physical_model.resource_models import evaluate_all, MODELS
from physical_model.resource_models import electrical, cooling, deck, mast, mass, datalinks, compute, timing
ROOT = Path(__file__).resolve().parents[1] / 'data'
def load(path):
    return json.loads((ROOT / path).read_text())

class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.specs = load('ship_specs.json')
        self.state = load('example_state.json')
        self.cards = {gid: load(f'../tests/fixtures/legacy_guest_manifests/{gid}.json') for gid in ('G1','G2','G3','G4','G5')}
        self.guests = [self.cards[x] for x in ('G1','G3','G4')]
    def run_model(self, module, guests=None):
        return module.evaluate(self.specs, self.state, self.guests if guests is None else guests)
    def current(self, gid):
        g = self.cards[gid]
        return g['modes'][g['mode']]
    def test_baseline(self):
        for module in MODELS[:-1]:
            self.assertEqual(self.run_model(module)['status'], 'PASS', module.__name__)
        self.assertEqual(self.run_model(timing)['status'], 'UNKNOWN')
    def test_missing_resources_never_pass(self):
        for module in MODELS:
            self.assertEqual(module.evaluate({}, {}, self.guests)['status'], 'UNKNOWN')
    def test_duplicate_ids(self):
        for module in MODELS:
            self.assertEqual(module.evaluate(self.specs,self.state,[self.guests[0]]*2)['status'],'UNKNOWN')
    def test_invalid_numeric(self):
        for value in (-1, float('nan'),float('inf'),True,'25',None):
            self.current('G1')['power_kw'] = value
            self.assertEqual(self.run_model(electrical)['status'],'UNKNOWN')
    def test_missing_demand(self):
        del self.current('G1')['power_kw']
        self.assertEqual(self.run_model(electrical)['status'], 'UNKNOWN')
    def test_generator_down(self):
        self.state['gensets_online']=1
        self.cards['G3']['mode']='charging'
        self.cards['G4']['mode']='recovery'
        guests=[self.cards[x] for x in ('G3','G4','G5')]
        r=self.run_model(electrical,guests)
        self.assertEqual(r['details']['demand_kw'],105)
        self.assertIn('continuous_reserve',r['binding_constraints'])
        self.cards['G5']['mode']='low_power'
        self.assertEqual(self.run_model(electrical,guests)['status'],'PASS')
    def test_lost_line(self):
        self.state['online_power_lines']=['port']
        self.assertIn('stbd.continuous',self.run_model(electrical)['binding_constraints'])
    def test_line_saturation_with_total_margin(self):
        m=self.current('G3');m['power_kw']=151
        r=self.run_model(electrical)
        self.assertLess(r['details']['demand_kw'],200)
        self.assertIn('port.continuous',r['binding_constraints'])
    def test_peak_is_bounded(self):
        m=self.current('G3');m['peak_extra_kw']=50;m['peak_duration_s']=61
        self.assertIn('G3.peak_duration',self.run_model(electrical)['binding_constraints'])
        m['peak_duration_s']=60
        self.assertEqual(self.run_model(electrical)['status'],'PASS')
        self.assertEqual(self.run_model(cooling)['status'],'UNKNOWN')
    def test_unsupported_speed(self):
        self.state['speed_band']='stopped'
        self.assertEqual(self.run_model(electrical)['status'],'UNKNOWN')
    def test_cooling_curve_and_fault(self):
        for t,expected in [(12,160),(21,140),(30,120)]:
            self.state['seawater_c']=t
            self.assertAlmostEqual(self.run_model(cooling)['details']['capacity_kw'],expected)
        self.state['cooling_fault']=True
        self.assertEqual(self.run_model(cooling)['details']['capacity_kw'],72)
    def test_heat_balance(self):
        self.current('G1')['heat_paths'][0]['kw']=0
        self.assertIn('G1.heat_balance',self.run_model(cooling)['binding_constraints'])
    def test_mast_air_limit(self):
        m=self.current('G1');m['power_kw']=2.1;m['heat_paths'][0]['kw']=2.1
        self.assertIn('mast3.air_heat',self.run_model(cooling)['binding_constraints'])
    def test_cooling_temperature_outside_curve(self):
        for t in (11,31):
            self.state['seawater_c']=t
            self.assertEqual(self.run_model(cooling)['status'],'UNKNOWN')
    def test_cooling_boundary(self):
        self.state['seawater_c']=30
        self.current('G3')['power_kw']=118
        self.current('G3')['heat_paths'][0]['kw']=118
        self.assertEqual(self.run_model(cooling)['status'],'PASS') # + G4=120 loop, G1 air
        self.current('G3')['power_kw']=118.1
        self.current('G3')['heat_paths'][0]['kw']=118.1
        self.assertEqual(self.run_model(cooling)['status'],'FAIL')
    def test_over_mass_starting_fixture(self):
        r=self.run_model(mass,[self.cards[x] for x in ('G2','G3','G4')])
        self.assertEqual(r['details']['demand_kg'],10040)
        self.assertIn('added_mass',r['binding_constraints'])
        self.assertEqual(r['details']['naval_stability'],'NOT_VERIFIED')
    def test_mass_component_consistency(self):
        self.cards['G1']['mass_kg']=100
        self.assertIn('G1.mass_balance',self.run_model(mass)['binding_constraints'])
    def test_mast_scarcity(self):
        self.assertIn('mast3.occupancy',self.run_model(mast,[self.cards['G1'],self.cards['G5']])['binding_constraints'])
    def test_reserved_mast(self):
        self.cards['G1']['placements'][0]['location']='mast1'
        self.assertEqual(self.run_model(mast)['status'],'FAIL')
    def test_unknown_placement(self):
        self.cards['G1']['placements'][0]['location']='nowhere'
        for module in (mast,deck,mass):
            self.assertEqual(self.run_model(module)['status'],'UNKNOWN')
    def test_deck_bay_occupancy(self):
        self.assertIn('bay2.occupancy',self.run_model(deck,[self.cards['G2'],self.cards['G5']])['binding_constraints'])
    def test_deck_dimensions(self):
        self.cards['G3']['placements'][0]['dimensions_m'][0]=7
        self.assertIn('G3.bay1.length',self.run_model(deck)['binding_constraints'])
    def test_false_half_bay_claim(self):
        g=copy.deepcopy(self.cards['G3']);g['id']='new';g['placements'][0]['units']=1
        self.cards['G3']['placements'][0]['units']=1
        self.assertIn('bay1.packed_length',self.run_model(deck,[self.cards['G3'],g])['binding_constraints'])
    def test_deck_flight_conditions(self):
        self.state.update(active_operations=['flight'],speed_kn=6)
        self.assertEqual(self.run_model(deck)['status'],'PASS')
        self.state['wind_kn']=26
        self.assertIn('flight.wind',self.run_model(deck)['binding_constraints'])
        self.state['active_operations']=['flight','ramp']
        self.assertIn('flight_ramp_exclusion',self.run_model(deck)['binding_constraints'])
    def test_silence_radio_blackout(self):
        self.state['emission']='silent'
        self.assertIn('satcom.bandwidth',self.run_model(datalinks)['binding_constraints'])
    def test_acoustic_drop(self):
        for field,value in [('noise','manoeuvring'),('deck_machinery',True),('layered_water',True)]:
            saved=self.state[field];self.state[field]=value
            self.assertEqual(self.run_model(datalinks)['status'],'FAIL')
            self.state[field]=saved
    def test_link_latency(self):
        self.state['links']['satcom']['latency_ms']=900
        self.assertIn('G1.satcom.latency',self.run_model(datalinks)['binding_constraints'])
    def test_no_link_pooling(self):
        self.current('G1')['datalinks']['satcom']['mbps']=9
        self.assertIn('satcom.bandwidth',self.run_model(datalinks)['binding_constraints'])
    def test_compute_node_failure(self):
        self.state['compute_nodes_online'].remove('node2')
        self.assertIn('node2.cores',self.run_model(compute)['binding_constraints'])
    def test_compute_fragmentation(self):
        c=self.current('G3')['compute'];c['cores']=26;c['allocations'][0]['cores']=26
        self.assertIn('node2.cores',self.run_model(compute)['binding_constraints'])
    def test_compute_allocation_balance(self):
        self.current('G3')['compute']['cores']=20
        self.assertIn('G3.cores.allocation_balance',self.run_model(compute)['binding_constraints'])
    def test_fractional_accelerator(self):
        self.current('G3')['compute']['allocations'][0]['accelerators']=.5
        self.assertEqual(self.run_model(compute)['status'],'UNKNOWN')
    def test_gpu_reserve_after_node_failure(self):
        self.state['compute_nodes_online'].remove('node4')
        for gid in ('G1','G3','G4'):
            c=self.current(gid)['compute']
            c['accelerators']=1
            c['allocations'][0]['accelerators']=1
        self.assertIn('online_rack.accelerators',self.run_model(compute)['binding_constraints'])
    def test_shared_storage_reserve(self):
        self.current('G3')['compute']['storage_tb']=17
        self.assertIn('shared_storage',self.run_model(compute)['binding_constraints'])
    def test_timing_evidence(self):
        self.state['timing']={k:{'worst_case_ms':v,'verified':True} for k,v in self.specs['timing_ms'].items()}
        self.assertEqual(self.run_model(timing)['status'],'PASS')
        self.state['timing']['safety_command']['worst_case_ms']=201
        self.assertIn('safety_command',self.run_model(timing)['binding_constraints'])
        del self.state['timing']['arbitration']
        self.assertTrue(any(c['status']=='UNKNOWN' for c in self.run_model(timing)['checks']))
    def test_no_mutation_and_replay(self):
        before=copy.deepcopy((self.specs,self.state,self.guests))
        a=evaluate_all(self.specs,self.state,self.guests)
        self.assertEqual(a,evaluate_all(self.specs,self.state,self.guests))
        self.assertEqual(before,(self.specs,self.state,self.guests))
        self.assertTrue(a['physical_feasible']) # Physical screening is separate from timing evidence
        self.assertFalse(a['timing_verified'])
        json.dumps(a,allow_nan=False)
    def test_not_installed_does_not_consume(self):
        self.cards['G1']['installed']=False
        self.assertEqual(self.run_model(electrical)['details']['demand_kw'],3)

if __name__=='__main__':
    unittest.main()
