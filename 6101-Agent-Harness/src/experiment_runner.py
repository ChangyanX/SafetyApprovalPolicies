"""Offline, multi-suite experiment planning. Does not execute benchmark episodes."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from agentdojo.attacks.attack_registry import ATTACKS
from agentdojo.task_suite.load_suites import get_suite, get_suites

from .policy import POLICY_LABELS


def _unique(values, label):
    if not values or len(values) != len(set(values)):
        raise ValueError(f'{label} must be non-empty and contain no duplicates')


def build_experiment_plan(
    benchmark_version: str = 'v1.2.2',
    suite_name: str | None = None,
    policies: list[str] | None = None,
    k_values: list[int] | None = None,
    *,
    suite_names: list[str] | None = None,
    attack_methods: list[str] | None = None,
    repeats: int = 1,
    include_clean: bool = True,
    include_attacked: bool = True,
) -> list[dict[str, Any]]:
    """Default to all suites; suite_name retains single-suite API compatibility.

    Attack methods must be fixed non-DoS methods. Manifest cells are planned,
    not a statement of attack feasibility or successful model execution.
    """
    policies = list(POLICY_LABELS) if policies is None else policies
    k_values = [0, 1, 3, 5] if k_values is None else k_values
    attack_methods = ['direct'] if attack_methods is None else attack_methods
    if suite_name is not None and suite_names is not None:
        raise ValueError('Use suite_name or suite_names, not both')
    available = get_suites(benchmark_version)
    selected = ([suite_name] if suite_name is not None else
                list(available) if suite_names is None else suite_names)
    for values, label in [(selected, 'suites'), (policies, 'policies'), (k_values, 'k_values')]:
        _unique(values, label)
    if any(name not in available for name in selected):
        raise ValueError(f'Unknown suite; choose from {tuple(available)}')
    if any(name not in POLICY_LABELS for name in policies):
        raise ValueError(f'Unknown policy; implemented policies are {POLICY_LABELS}')
    if any(type(k) is not int or k < 0 for k in k_values):
        raise ValueError('k_values must contain non-negative integers')
    if type(repeats) is not int or repeats < 1:
        raise ValueError('repeats must be a positive integer')
    if not include_clean and not include_attacked:
        raise ValueError('Select clean and/or attacked conditions')
    if include_attacked:
        _unique(attack_methods, 'attack_methods')
        if any(name not in ATTACKS or name == 'manual' for name in attack_methods):
            raise ValueError('Choose registered non-interactive attack methods')
    plan = []
    for name in selected:
        suite = get_suite(benchmark_version, name)
        if include_attacked:
            for method in attack_methods:
                if ATTACKS[method].is_dos_attack:
                    raise ValueError('DoS methods require a separate manifest/scoring protocol')
        conditions = [('clean', '', '')] if include_clean else []
        if include_attacked:
            conditions += [('attacked', method, injection)
                           for method in attack_methods for injection in suite.injection_tasks]
        for user_task in suite.user_tasks:
            for condition, attack, injection in conditions:
                for policy in policies:
                    for k in k_values:
                        for repeat in range(repeats):
                            row = dict(benchmark_version=benchmark_version, suite=name,
                                       user_task_id=user_task, condition=condition,
                                       attack=attack, injection_task_id=injection,
                                       policy=policy, k=k, repeat=repeat)
                            digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                            row.update(episode_id='ep_' + digest, status='pending', error='')
                            plan.append(row)
    return plan


def save_plan_csv(plan, output_path='runs/r5_multisuite_experiment_plan.csv', *, overwrite=False) -> Path:
    if not plan:
        raise ValueError('Cannot save an empty experiment plan')
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects existing status/results unless deliberately replaced.
    with path.open('w' if overwrite else 'x', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, fieldnames=list(plan[0]))
        writer.writeheader()
        writer.writerows(plan)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark-version', default='v1.2.2')
    parser.add_argument('--suite', action='append', dest='suites', help='Repeat to select suites; default: all')
    parser.add_argument('--policy', action='append', dest='policies', choices=POLICY_LABELS)
    parser.add_argument('--k', action='append', dest='k_values', type=int)
    parser.add_argument('--attack', action='append', dest='attacks')
    parser.add_argument('--repeats', type=int, default=1)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--clean-only', action='store_true')
    mode.add_argument('--attacked-only', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('runs/r5_multisuite_experiment_plan.csv'))
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args(argv)
    try:
        plan = build_experiment_plan(args.benchmark_version, policies=args.policies,
                                    k_values=args.k_values, suite_names=args.suites,
                                    attack_methods=args.attacks, repeats=args.repeats,
                                    include_clean=not args.attacked_only,
                                    include_attacked=not args.clean_only)
        path = save_plan_csv(plan, args.output, overwrite=args.overwrite)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    print(f'Planned {len(plan)} episodes across {len({row["suite"] for row in plan})} suites: {path.resolve()}')
    print('Planning only: no model requests or benchmark episodes executed.')


if __name__ == '__main__':
    main()
