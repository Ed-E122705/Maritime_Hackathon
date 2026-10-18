# Create a GitHub review branch (do not replace main)

Use your **current local clone** of `Ed-E122705/Maritime_Hackathon` on your Mac or
Qualcomm board. Make sure uncommitted work is backed up/committed first.

```bash
cd ~/Maritime_Hackathon
git status --short            # should be empty
git fetch origin
git switch -c integrate-governor-verifier origin/main
```

Extract **this overlay ZIP** into the repository *root*, not the ZIP's enclosing
folder and not into `physical_model/`. Example for a ZIP in Downloads:

```bash
unzip -o ~/Downloads/VesselOS_D1-D6_Integration_With_D1_Verifier.zip -d .
git status --short
git diff --stat
```

Review unexpected changes before committing. The ZIP adds the integrated governor
and dashboard and the isolated D1 reference, without replacing the existing
canonical ship, guest, or physical-model source files.

```bash
git add governor dashboard config scenarios tests integration_tests docs verification \
    requirements.txt Makefile INTEGRATION_README.md INTEGRATION_TEST_REPORT.md BRANCH_INSTALL.md
git commit -m 'Integrate decision governor dashboard and independent D1 verifier'
git push -u origin integrate-governor-verifier
```

Run tests on the **Qualcomm board** in the branch checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s physical_model/tests -v
.venv/bin/python -m unittest discover -s integration_tests -v
.venv/bin/python -m pytest -q tests
.venv/bin/python -m pytest -q verification/d1_reference/tests
.venv/bin/python -m governor.cli admit --candidate G4 --priority rescue --alternatives 0
.venv/bin/python dashboard/app.py --port 5050
```

No GitHub changes have been made by preparing this overlay. Test on hardware before
considering a pull request to main; passing isolated solver tests is not a
safety certification.

## Added features from the newer READY package

The integrated dashboard includes a G6 monitoring snapshot button. The installation safeguard is unchanged; G6 cannot be newly installed by D1 until its unknown crew, permission and timing fields are resolved. `docs/SCENARIO_C_CREW_POLICY.md` documents the D5 example.
