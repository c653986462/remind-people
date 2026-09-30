"""Backport the scheduler guard to legacy release copies before starting API slots.

Old releases ignore SCHEDULER_ENABLED. Preserve their entire startup/migration
logic and only guard the recognised scheduler statements. Unknown layouts fail
closed before a deployment can switch traffic.
"""
import ast
from pathlib import Path
import sys


def guard_legacy_scheduler(source: str) -> str:
    tree = ast.parse(source)
    lifespan = next((node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                     and node.name == 'lifespan'), None)
    if lifespan is None:
        raise ValueError('Missing application lifespan')
    # Native support or our prior backport: do not patch a release twice.
    for node in lifespan.body:
        if isinstance(node, ast.If):
            if any(isinstance(item, ast.Attribute) and item.attr == 'scheduler_enabled'
                   for item in ast.walk(node.test)):
                return source
            if 'SCHEDULER_ENABLED' in ast.get_source_segment(source, node.test):
                return source

    def scheduler_call(statement, name):
        return (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Attribute)
                and isinstance(statement.value.func.value, ast.Name)
                and statement.value.func.value.id == 'scheduler'
                and statement.value.func.attr == name)

    starts = [i for i, node in enumerate(lifespan.body) if scheduler_call(node, 'add_job')]
    if not starts:
        raise ValueError('Unrecognised legacy scheduler layout')
    first = starts[0]
    start = next((i for i, node in enumerate(lifespan.body) if scheduler_call(node, 'start')), None)
    shutdown = next((node for node in lifespan.body if scheduler_call(node, 'shutdown')), None)
    if start is None or shutdown is None or start < first:
        raise ValueError('Unrecognised legacy scheduler layout')
    for node in lifespan.body[first:start + 1]:
        catchup = (isinstance(node, ast.Expr) and isinstance(node.value, ast.Await)
                   and isinstance(node.value.value, ast.Call)
                   and isinstance(node.value.value.func, ast.Name)
                   and node.value.value.func.id == 'scheduled_due_date_check')
        if not (scheduler_call(node, 'add_job') or scheduler_call(node, 'start') or catchup):
            raise ValueError('Unexpected statement in legacy scheduler startup')
    if not any(isinstance(node, ast.Import) and any(alias.name == 'os' for alias in node.names)
               for node in tree.body):
        raise ValueError('Legacy application does not import os')

    lines = source.splitlines(keepends=True)
    edits = [
        (lifespan.body[first].lineno - 1, lifespan.body[start].end_lineno,
         '    if os.environ.get("SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:\n'),
        (shutdown.lineno - 1, shutdown.end_lineno, '    if scheduler.running:\n'),
    ]
    for begin, end, guard in sorted(edits, reverse=True):
        lines[begin:end] = [guard] + ['    ' + line for line in lines[begin:end]]
    result = ''.join(lines)
    ast.parse(result)
    return result


def prepare_release(release: Path):
    release = release.resolve(strict=True)
    if not release.is_relative_to(Path('/opt/certificate-manager/releases')):
        raise ValueError('Only an immutable release copy can be prepared')
    main = release / 'app/main.py'
    if main.is_symlink() or not main.is_file():
        raise ValueError('Missing regular main.py')
    source = main.read_text(encoding='utf-8')
    result = guard_legacy_scheduler(source)
    if result != source:
        backup = main.with_name('main.py.before-scheduler-guard')
        if backup.exists():
            raise ValueError('Unexpected existing scheduler guard backup')
        backup.write_text(source, encoding='utf-8')
        backup.chmod(0o640)
        main.write_text(result, encoding='utf-8')
        print(f'Legacy scheduler guard applied to {release}')
    else:
        print(f'Scheduler guard already present in {release}')


if __name__ == '__main__':
    prepare_release(Path(sys.argv[1]))
