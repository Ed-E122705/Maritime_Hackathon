"""Run the ADD-ON using original G1–G5 manifests and an operating snapshot."""
import argparse
import json
from pathlib import Path
from physical_model.manifest_adapter import evaluate_canonical

def main():
    parser=argparse.ArgumentParser(description='Run VesselOS physical/operational feasibility snapshot')
    parser.add_argument('--runtime',type=Path,help='JSON selections/activities; defaults to data/sample_runtime.json')
    parser.add_argument('--guest-dir',type=Path,help='Directory of your unmodified canonical G*.json files')
    parser.add_argument('--output',type=Path,help='Save full JSON report at this location')
    parser.add_argument('--verbose',action='store_true',help='Print the whole JSON report')
    args=parser.parse_args()
    report=evaluate_canonical(guest_dir=args.guest_dir,runtime_path=args.runtime)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if args.verbose:
        print(json.dumps(report,indent=2,allow_nan=False))
    else:
        print('Installed:', ', '.join(report['installed_guest_ids']))
        print('Conditional simulation snapshot:', report['status'])
        print('Source evidence:', report['source_evidence_status'])
        print('Full admission:', report['full_admission_status'])
        print('Execution-time evidence:',report['timing_status'])
        for key,value in report['resources'].items():
            print(f'  {key:12s} {value["status"]:7s} {", ".join(value["binding_constraints"][:3])}')
        print('Assumptions active:', ', '.join(report['assumption_ids_used']))
        print('See data/ASSUMPTIONS_AND_JUSTIFICATIONS.md for limitations and provenance.')

if __name__=='__main__':
    main()
