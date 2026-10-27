import argparse
import sys

from zugup.config import default_config
from zugup.web import app as web


def main(argv=None):
    parser = argparse.ArgumentParser(prog="zugup")
    parser.add_argument("--port", type=int, default=web.DEFAULT_PORT)
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args(argv)
    web.serve(default_config(), args.port, dev=args.dev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
