# Uses the project virtualenv once `make setup` has created it
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt
	@echo "Setup done. Next: make test"


demo:
	$(PY) -m governor.cli admit --candidate G4
	$(PY) -m governor.cli admit --candidate G4 --set card.G4.resources.power_modes.charging_initial.power_kw.nominal=70 --alternatives 3
	$(PY) -m governor.cli admit --candidate G4 --state location=at_sea crew=6 --alternatives 0
	$(PY) -m governor.cli admit --candidate G4 --state location=at_sea crew=0 --alternatives 0
	$(PY) -m governor.cli b --priority survey
	$(PY) -m governor.cli b --priority rescue

test:
	$(PY) -m pytest -q tests

results:
	$(PY) -m governor.report

defaults:
	$(PY) -m governor.cli defaults

account:
	$(PY) -m governor.account

.PHONY: setup demo test results defaults account dashboard

dashboard:
	$(PY) dashboard/app.py --port $(or $(PORT),5050)

smoke:
	$(PY) -m unittest discover -s physical_model/tests -q
	$(PY) -m unittest discover -s integration_tests -v

.PHONY: smoke
