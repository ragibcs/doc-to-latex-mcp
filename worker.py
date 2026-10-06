import json
import os
import resource
import sys
from pathlib import Path


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (90, 95))
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (120 * 1024 * 1024, 120 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['OMP_NUM_THREADS'] = '1'
    import documents
    import latex_engine

    job = Path(sys.argv[1]).resolve()
    action = sys.argv[2]
    options = json.loads(sys.argv[3])
    operations = {'inspect': documents.inspect, 'analyze': documents.analyze, 'assets': documents.assets, 'tables': documents.tables, 'equations': documents.equations, 'generate': latex_engine.generate, 'compile': latex_engine.compile_project, 'compare': latex_engine.compare}
    if action not in operations:
        raise ValueError('Unknown operation.')
    result = operations[action](job, **options)
    (job / 'worker-result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
