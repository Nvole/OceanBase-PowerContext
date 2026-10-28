import argparse
import json
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))
os.chdir(project_root)


def configure_database(connection_file=None, sqlite=False):
    if sqlite:
        os.environ['SEEKDB_HOST'] = ''
    elif connection_file:
        connection = json.loads(Path(connection_file).read_text(encoding='utf-8-sig'))
        os.environ.update(
            SEEKDB_HOST=connection['host'],
            SEEKDB_PORT=str(connection.get('port', 2881)),
            SEEKDB_USER=connection['user'],
            SEEKDB_PASSWORD=connection['password'],
            SEEKDB_DATABASE='qoder_research',
        )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Start the research document assistant.')
    parser.add_argument('--connection-file', type=Path)
    parser.add_argument('--sqlite', action='store_true')
    parser.add_argument('--import-examples', action='store_true')
    parser.add_argument('--port', type=int, default=8000)
    arguments = parser.parse_args()
    if arguments.connection_file and arguments.sqlite:
        parser.error('--connection-file and --sqlite cannot be combined')
    configure_database(arguments.connection_file, arguments.sqlite)
    if arguments.import_examples:
        from scripts.import_examples import import_examples
        import_examples()
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=arguments.port)
