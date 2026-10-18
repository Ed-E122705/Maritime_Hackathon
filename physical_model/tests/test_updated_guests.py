"""Regressions for updated manifests, evidence gaps and public snapshot APIs."""
import copy
import unittest
from physical_model.manifest_adapter import ROOT, load_json, load_canonical_guests, normalize_guests
from physical_model.ship_state import ShipState
from physical_model.snapshot import build_snapshot, load_snapshot
from physical_model.resource_models.common import InputError


class UpdatedGuestTests(unittest.TestCase):
    def setUp(self):
        self.specs = load_json(ROOT / 'physical_model/data/ship_specs.json')
        self.profiles = load_json(ROOT / 'physical_model/data/resource_profiles.json')
        self.guests = load_canonical_guests()
        self.state = ShipState.from_files()

    def card(self, gid):
        return next(g for g in self.guests if g['id'] == gid)

    def select(self, *ids):
        self.state = self.state.updated({'guests': {g['id']: {'installed': g['id'] in ids} for g in self.guests}})

    def normalize(self):
        return normalize_guests(self.guests, self.state.to_dict(), self.profiles)[0]

    def evaluate(self):
        return build_snapshot(self.specs, self.state, self.guests, self.profiles)

    def test_explicit_operation_mappings_infer_only_declared_mode(self):
        for card in self.guests:
            for operation in card['operational_modes']:
                expected = operation.get('power_mode_id')
                if expected is None:
                    continue
                with self.subTest(guest=card['id'], operation=operation['id']):
                    self.select(card['id'])
                    values = self.state.to_dict()
                    choice = values['guests'][card['id']]
                    # A newly added guest may not have a selection in the sample runtime.
                    # This test isolates operation-to-power mapping; use its only declared
                    # placement explicitly rather than letting the model guess a location.
                    if not choice.get('placement'):
                        configs = card['placement']['configurations']
                        self.assertEqual(len(configs), 1, 'Explicit placement needed for multi-config guest')
                        choice['placement'] = configs[0]['id']
                    choice.pop('power_mode', None)
                    choice['operation'] = operation['id']
                    normalized, _ = normalize_guests(self.guests, values, self.profiles)
                    self.assertEqual(normalized[0]['mode'], expected)

    def test_winch_cannot_use_continuous_power(self):
        self.select('G2')
        self.state = self.state.updated({'guests': {'G2': {'operation': 'winch_operation', 'power_mode': 'continuous'}}})
        with self.assertRaisesRegex(InputError, 'requires power_mode winch_operation'):
            self.normalize()

    def test_null_operation_mapping_does_not_guess_power(self):
        self.select('G4')
        values = self.state.to_dict()
        values['guests']['G4']['operation'] = 'in_flight'
        del values['guests']['G4']['power_mode']
        with self.assertRaises(InputError):
            normalize_guests(self.guests, values, self.profiles)

    def test_g5_allowed_power_mapping_is_enforced(self):
        self.select('G5')
        new = copy.deepcopy(self.card('G5')['resources']['power_modes'][0])
        new['id'] = 'new_mode'
        self.card('G5')['resources']['power_modes'].append(new)
        self.state = self.state.updated({'guests': {'G5': {'power_mode': 'new_mode'}}})
        with self.assertRaisesRegex(InputError, 'one of'):
            self.normalize()

    def test_source_backbone_and_shore_rates_propagate(self):
        self.select('G1', 'G2', 'G3', 'G5')
        changes = [('G1', 'backbone', 'nominal', 75), ('G2', 'shore_link_transport_unspecified', 'nominal', .7),
                   ('G3', 'cradle_backbone', 'nominal', 125), ('G5', 'satcom', 'max', 7)]
        for gid, kind, bound, value in changes:
            link = next(x for x in self.card(gid)['resources']['data_links'] if x['type'] == kind)
            link['bandwidth_mbps'][bound] = value
        normalized = {g['id']: g['modes'][g['mode']] for g in self.normalize()}
        for gid, host_link, expected in [('G1','backbone',75), ('G2','satcom',.7), ('G3','backbone',125), ('G5','satcom',7)]:
            self.assertEqual(normalized[gid]['datalinks'][host_link]['mbps'], expected)

    def test_g5_cooling_and_bandwidth_do_not_follow_invented_scaling(self):
        self.state = ShipState.from_files(runtime_path=ROOT / 'scenarios/B_generator_trip_overload.json').updated(
            {'seawater_c': 30, 'cooling_fault': True})
        full = self.evaluate()
        self.assertEqual(full['resources']['cooling']['details']['loop_demand_kw'], 105)
        self.assertEqual(full['resources']['cooling']['details']['remaining_kw'], -33)
        self.state = self.state.updated({'guests': {'G5': {'power_mode': 'low_power'}}})
        low = self.evaluate()
        self.assertEqual(low['resources']['cooling']['details']['loop_demand_kw'], 68)
        self.assertEqual(low['resources']['cooling']['details']['remaining_kw'], 4)
        self.assertEqual(low['resources']['datalinks']['details']['demand_mbps']['satcom'], 6)

    def test_survey_estimate_and_compute_are_independent_of_standby(self):
        self.select('G3')
        self.state = self.state.updated({'guests': {'G3': {'operation': 'surveying'}}})
        self.profiles['guest_resource_profiles']['G3']['survey_power_kw'] = 6
        mode = self.normalize()[0]['modes']['standby']
        self.assertEqual(mode['power_kw'], 6)
        self.assertEqual(mode['heat_paths'][0]['kw'], 6)
        self.assertEqual(mode['compute']['cores'], 8)

    def test_declared_survey_mapping_replaces_synthetic_power(self):
        self.select('G3')
        self.card('G3')['operational_modes'][0]['power_mode_id'] = 'standby'
        self.card('G3')['resources']['power_modes'][0]['power_kw']['nominal'] = 4
        self.profiles['guest_resource_profiles']['G3']['survey_power_kw'] = 99
        self.state = self.state.updated({'guests': {'G3': {'operation': 'surveying'}}})
        self.assertEqual(self.normalize()[0]['modes']['standby']['power_kw'], 4)

    def test_compute_source_overrides_profiles_and_decimal_storage_conversion(self):
        self.select('G1')
        self.card('G1')['resources']['compute'] = {'cpu_cores': 7, 'ram_gb': 12, 'accelerator_units': 1, 'storage_gb': 500}
        self.profiles['guest_resource_profiles']['G1']['compute_by_mode'] = {}
        demand = self.normalize()[0]['modes']['active']['compute']
        self.assertEqual((demand['cores'], demand['ram_gb'], demand['accelerators'], demand['storage_tb']), (7,12,1,.5))

    def test_missing_compute_field_is_not_zero(self):
        self.select('G1')
        del self.profiles['guest_resource_profiles']['G1']['compute_by_mode']['active']['accelerators']
        with self.assertRaisesRegex(InputError, 'missing compute demand'):
            self.normalize()

    def test_video_selection_respects_source_range(self):
        self.select('G4')
        self.state = self.state.updated({'guests': {'G4': {'operation': 'in_flight'}}})
        self.profiles['g4_los_nominal_mbps'] = 21
        with self.assertRaisesRegex(InputError, 'outside its declared range'):
            self.normalize()
        self.card('G4')['resources']['data_links'][0]['bandwidth_mbps']['nominal'] = 12
        self.assertEqual(self.normalize()[0]['modes']['standby']['datalinks']['los']['mbps'], 12)

    def test_real_peak_requires_separate_duration_evidence(self):
        self.select('G1')
        self.card('G1')['resources']['power_modes'][0]['power_kw']['peak'] = 2
        report = self.evaluate()
        self.assertEqual(report['resources']['electrical']['status'], 'UNKNOWN')
        self.profiles['guest_resource_profiles']['G1']['peak_duration_s_by_mode'] = {'active': 30}
        report = self.evaluate()
        self.assertEqual(report['resources']['electrical']['status'], 'PASS')
        self.assertEqual(report['resources']['cooling']['status'], 'UNKNOWN')

    def test_duplicate_assembly_assignment_is_rejected(self):
        self.select('G4')
        config = self.card('G4')['placement']['configurations'][0]
        config['assignments'].append(copy.deepcopy(config['assignments'][0]))
        with self.assertRaisesRegex(InputError, 'exactly once'):
            self.normalize()

    def test_updated_conflict_id_is_evaluated(self):
        self.select('G2', 'G4')
        self.state = self.state.updated({'guests': {'G2': {'operation':'winch_operation','power_mode':'winch_operation'},
                                                   'G4': {'operation':'launch_recovery'}},
                                         'active_operations':['flight'], 'speed_kn':6, 'deck_machinery':True,
                                         'guest_state':{'G2': {'mode_elapsed_minutes':1}}})
        report = self.evaluate()
        self.assertIn('G2.G4.operating_conflict', report['resources']['operational']['binding_constraints'])

    def test_battery_deadline_uses_elapsed_time_and_source_event(self):
        self.select('G4')
        self.state = self.state.updated({'guests': {'G4': {'operation':'launch_recovery'}},
                                         'active_operations':['flight'], 'speed_kn':6,
                                         'guest_state':{'G4': {'battery_percent':18,'eta_to_landing_min':9,'minutes_since_low_battery':4}}})
        self.assertIn('G4.emergency_recovery_eta', self.evaluate()['resources']['operational']['binding_constraints'])
        self.card('G4')['special_events'][0]['recovery_deadline_minutes'] = 15
        self.assertEqual(self.evaluate()['resources']['operational']['status'], 'PASS')
        self.state = self.state.updated({'guest_state': {'G4': {'minutes_since_low_battery':None}}})
        self.assertEqual(self.evaluate()['resources']['operational']['status'], 'UNKNOWN')

    def test_drone_mass_and_charge_duration_are_not_hardcoded(self):
        self.select('G3', 'G4')
        self.card('G4')['assembly']['components'][0]['mass_kg'] = 160
        self.card('G3')['resources']['power_modes'][1]['max_duration_minutes'] = 80
        self.state = self.state.updated({'mode_change_requests':[{'guest_id':'G3','from_mode':'charging','to_mode':'standby','elapsed_minutes':60}]})
        binding = self.evaluate()['resources']['operational']['binding_constraints']
        self.assertIn('G4.drone_mass', binding)
        self.assertIn('G3.noninterruptible_charge', binding)

    def test_installation_uses_updated_vehicle_target_and_duration(self):
        self.select('G3')
        request = {'guest_id':'G3','operation':'swap_vehicle_only','operation_target':'vehicle','available_minutes':44}
        self.state = self.state.updated({'install_requests':[request], 'speed_kn':6, 'wind_kn':16,'crew':6})
        self.assertIn('installation.duration', self.evaluate()['resources']['operational']['binding_constraints'])
        request['available_minutes'] = 45
        self.state = self.state.updated({'install_requests':[request]})
        self.assertEqual(self.evaluate()['resources']['operational']['status'], 'PASS')
        request['operation'] = 'install_assembly'
        self.state = self.state.updated({'install_requests':[request]})
        self.assertIn('installation.at_sea_physical_type', self.evaluate()['resources']['operational']['binding_constraints'])

    def test_uninstalled_candidate_installation_can_be_checked_in_port(self):
        self.select()
        self.state = self.state.updated({'ship_location':'in_port', 'crew':6, 'install_requests':[
            {'guest_id':'G2','operation':'install_assembly','available_minutes':360}]})
        report = self.evaluate()
        self.assertEqual(report['resources']['operational']['status'], 'PASS')
        self.assertEqual(report['installed_guest_ids'], [])

    def test_guest_processing_requirement_is_separate_from_host_timings(self):
        self.select('G1')
        self.card('G1')['resources']['response_time']['max_processing_latency_ms'] = 20
        self.state = self.state.updated({'guest_state': {'G1': {'processing_timing':{'worst_case_ms':21,'verified':True}}},
                                         'timing':{key:{'worst_case_ms':1,'verified':True} for key in self.specs['timing_ms']}})
        self.assertEqual(self.evaluate()['timing_status'], 'FAIL')

    def test_physical_pass_preserves_evidence_unknown(self):
        report = self.evaluate()
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['assessment_status'], 'UNKNOWN')
        self.assertEqual(report['source_evidence_status'], 'UNKNOWN')
        self.assertEqual(report['full_admission_status'], 'NOT_EVALUATED')
        self.assertTrue(report['unresolved_constraints'])

    def test_snapshot_does_not_mutate_and_is_replayable(self):
        before = copy.deepcopy((self.specs, self.guests, self.profiles))
        report = self.evaluate()
        self.assertEqual(report, self.evaluate())
        self.assertEqual(before, (self.specs, self.guests, self.profiles))
        self.assertEqual(report, load_snapshot())

    def test_state_updates_copy_nested_values_and_preserve_siblings(self):
        changed = self.state.updated({'links':{'satcom':{'available_mbps':2}}})
        values = changed.to_dict()
        self.assertEqual(values['links']['satcom']['latency_ms'], 800)
        values['links']['satcom']['available_mbps'] = 999
        self.assertEqual(changed.to_dict()['links']['satcom']['available_mbps'], 2)
        self.assertEqual(self.state.to_dict()['links']['satcom']['available_mbps'], 8)
        first = self.evaluate()['input_sha256']['state']
        self.state = changed
        self.assertNotEqual(first, self.evaluate()['input_sha256']['state'])

    def test_invalid_or_missing_state_cannot_pass(self):
        for bad in (float('nan'), float('inf')):
            with self.assertRaises(InputError):
                ShipState.from_dict({'speed_kn':bad})
        self.state = ShipState.from_dict({'guests':{}})
        self.assertEqual(self.evaluate()['status'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
