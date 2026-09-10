"""Print the effective deployment plan without making network requests."""
import argparse
import json
import os
import sys

from .config import resolve
from .settings import DEFAULTS


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config")
    result.add_argument("--endpoint", default=DEFAULTS["endpoint"])
    result.add_argument("--retries", type=int, default=DEFAULTS["retries"])
    result.add_argument("--label", default=DEFAULTS["label"])
    return result


def plan(argv, environment):
    return resolve(parser().parse_args(argv), environment)


def main(argv=None):
    try:
        settings = plan(argv, os.environ)
    except (ValueError, OSError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(settings.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
