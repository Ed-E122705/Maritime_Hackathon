"""v3 dashboard integration must retain canonical evidence/safety caveats."""
import pytest
from dashboard.app import app
from governor import loader

@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    return app.test_client()

def test_meta_g6_assumed_priority_and_weight_basis(client):
    j=client.get('/api/meta').get_json()
    assert 'G6' in j['guests']
    assert all(p['G6']==10 for p in j['priorities'].values())
    assert j['weight_basis']['survey']['guests']['G6']['safety_critical']

def test_capacity_check_g1g2g3_g4_exceeds_mass(client):
    inst={'G1':'mast','G2':'bay2','G3':'bay1'}
    resp=client.post('/api/check',json={'installed':inst,'adds':{'G4':'auto'},'priority':'survey'})
    assert resp.status_code == 200, resp.get_json()
    out=resp.get_json()
    assert not out['fits'] and 'mass' in out['binding']
    assert out['alternatives']
    assert out['assessment_note']

def test_capacity_fit_not_full_admission(client):
    inst={'G1':'mast','G2':'bay2','G3':'bay1'}
    out=client.post('/api/check',json={'installed':inst,'adds':{},'priority':'survey'}).get_json()
    assert out['fits']
    assert out['admission_status']=='NOT_EVALUATED'

def test_g6_installation_stays_not_now_even_if_capacity_checked(client):
    inst={}
    out=client.post('/api/check',json={'installed':inst,'adds':{'G6':'auto'},'priority':'survey'}).get_json()
    assert out['admission_status']=='NOT-NOW'
    assert 'Installation not authorized for G6' in out['installation_warning']
    assert 'admission' in out['assessment_note']
    assert loader.load_guest_data(loader.load_raw())['G6'].safety_critical

def test_physical_g6_endpoint_preserved(client):
    out=client.get('/api/physical-g6')
    assert out.status_code==200
    assert out.get_json()['full_admission_status']=='NOT_EVALUATED'
