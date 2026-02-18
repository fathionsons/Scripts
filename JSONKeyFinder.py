from automation_cli import run_task
import sys


def _pause():
    if not sys.stdin or not sys.stdin.isatty():
        return
    try:
        input("Work is done. Press Enter to close or continue.")
    except EOFError:
        pass


if __name__ == "__main__":
    try:
        run_task("json_key_finder")
    finally:
        _pause()
