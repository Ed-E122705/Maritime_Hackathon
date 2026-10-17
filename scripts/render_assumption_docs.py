"""Generate the readable register and working CSV from assumptions.json.

Run from any directory. --check verifies generated files without changing them.
This does not invent or refresh evidence: edit/review the register first.
"""
import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / 'physical_model/data/assumptions.json'


def sources(row):
    return '; '.join(x['file'] + '#' + x['pointer'] for x in row.get('source_refs', []))


def value_text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def render(register):
    lines = ['# Assumptions and justifications — updated G1–G5', '',
             register['scope'], '',
             'The guest manifests supply facts; `resource_profiles.json` supplies explicit demonstration choices. '
             'Reducing unjustified inference matters more than reducing the number of JSON keys. '
             'No random noise or unsupported probability distribution is added.', '',
             '**Interpretation:** `status` is a conditional physical/operational simulation; '
             '`assessment_status` also includes timing and missing source evidence. '
             'A simulation PASS is not a full admission decision.', '',
             f"This register has {len(register['assumptions'])} assumption/scenario records, "
             f"{len(register['source_rules'])} source-rule records and "
             f"{len(register['unresolved_inputs'])} unresolved input groups.", '',
             '## Corrected issues', '']
    for finding in register['findings']:
        lines.extend([f"- **{finding['id']}** — {finding['finding']} {finding['resolution']}"])
    for title, key in [('Assumptions and scenario choices', 'assumptions'),
                       ('Facts and rules retained from source inputs', 'source_rules')]:
        lines.extend(['', '## ' + title, ''])
        for row in register[key]:
            lines.extend([f"### {row['id']} — {row['topic']}", '',
                          f"Classification: `{row['classification']}`", '',
                          '**Current choice:** ' + value_text(row['current_value']), '',
                          '**Why:** ' + row['why'], '',
                          '**Effect on results:** ' + row['effect_on_results'], '',
                          '**How to replace or verify it:** ' + row['resolution'], ''])
            if row.get('sensitivity') is not None:
                lines.extend(['**Suggested sensitivity inputs:** ' + value_text(row['sensitivity']), ''])
            lines.append('Source references:')
            lines.append('')
            for source in row.get('source_refs', []):
                lines.append(f"- [{source['file']}](../{source['file']}) at `{source['pointer'] or '/'}`")
            lines.extend(['', 'Implementation: ' + ', '.join('`' + x + '`' for x in row['implementation_refs']), ''])
    lines.extend(['## Unresolved inputs', ''])
    for row in register['unresolved_inputs']:
        lines.append(f"- **{row['id']} — {row['topic']}:** {row['action']}")
    lines.extend(['', '## Updating this register', '', register['integration'], '',
                  '```bash', 'python3 scripts/render_assumption_docs.py',
                  'python3 scripts/audit_assumptions.py',
                  'python3 scripts/run_sensitivity.py', '```', '',
                  'The sensitivity JSON contains actual model evaluations. Scenario values are explicit test '
                  'inputs, not confidence intervals or measured variability.', ''])
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['id', 'record_group', 'classification', 'topic', 'current_value', 'why',
                     'effect_on_results', 'resolution', 'source_references', 'implementation', 'sensitivity'])
    for group in ('assumptions', 'source_rules'):
        for row in register[group]:
            writer.writerow([row['id'], group, row['classification'], row['topic'],
                             value_text(row['current_value']), row['why'], row['effect_on_results'],
                             row['resolution'], sources(row), '; '.join(row['implementation_refs']),
                             value_text(row.get('sensitivity'))])
    return {'data/ASSUMPTIONS_AND_JUSTIFICATIONS.md': '\n'.join(lines),
            'data/PHYSICAL_ACCOUNT_WORKING.csv': output.getvalue()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    generated = render(json.loads(REGISTER.read_text(encoding='utf-8')))
    stale = []
    for file, contents in generated.items():
        path = ROOT / file
        if args.check:
            if not path.exists() or path.read_bytes() != contents.encode('utf-8'):
                stale.append(file)
        else:
            path.write_bytes(contents.encode('utf-8'))
    if stale:
        raise SystemExit('Stale generated register: ' + ', '.join(stale))
    print('Assumption documents ' + ('match the register.' if args.check else 'regenerated.'))


if __name__ == '__main__':
    main()
