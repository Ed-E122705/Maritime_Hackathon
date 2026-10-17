"""Aggregate resource checks and expose qualified constraints to a decision engine."""
from .resource_models import evaluate_all


def combine_statuses(statuses):
    values = list(statuses)
    return 'FAIL' if 'FAIL' in values else ('UNKNOWN' if 'UNKNOWN' in values else 'PASS')


def evaluate(specs, state, normalized_guests):
    """Return the existing physical status plus independent timing and all blockers.

    A list of all FAIL/UNKNOWN checks is supplied, even when a resource's primary
    binding_constraints list contains only failures. This preserves missing
    evidence alongside known infeasibility.
    """
    report = evaluate_all(specs, state, normalized_guests)
    report['overall_model_status'] = combine_statuses(
        [report['status'], report['timing_status']])
    report['constraint_violations'] = []
    report['unresolved_constraints'] = []
    for resource, result in report['resources'].items():
        for check in result['checks']:
            if check['status'] == 'PASS':
                continue
            item = dict(check, resource=resource, constraint_id=resource + '.' + check['name'])
            destination = 'constraint_violations' if check['status'] == 'FAIL' else 'unresolved_constraints'
            report[destination].append(item)
    return report

