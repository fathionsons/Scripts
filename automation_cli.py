import argparse
import base64
import csv
import datetime as dt
import filecmp
import hashlib
import html
import json
import os
import pathlib
import random
import re
import shutil
import socket
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile


def _p(path):
    return pathlib.Path(path).expanduser()


def _ensure_dir(path):
    _p(path).mkdir(parents=True, exist_ok=True)


def _iter_files(path, recursive=True):
    path = _p(path)
    if path.is_file():
        yield path
        return
    if not path.exists():
        return
    if recursive:
        for root, _, files in os.walk(path):
            for name in files:
                yield pathlib.Path(root) / name
    else:
        for child in path.iterdir():
            if child.is_file():
                yield child


def _read_text(path):
    return _p(path).read_text(encoding="utf-8", errors="ignore")


def _write_text(path, text):
    _p(path).write_text(text, encoding="utf-8", errors="ignore")


def _format_bytes(num):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} PB"


def _hash_file(path, algo="sha256", chunk_size=1024 * 1024):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _print_kv(title, value):
    print(f"{title}: {value}")


TASKS = {}


def register_task(name, description, add_args, handler):
    TASKS[name] = {
        "description": description,
        "add_args": add_args,
        "handler": handler,
    }


def run_task(name, argv=None):
    if name not in TASKS:
        raise SystemExit(f"Unknown task: {name}")
    task = TASKS[name]
    parser = argparse.ArgumentParser(prog=name, description=task["description"])
    if task["add_args"] is not None:
        task["add_args"](parser)
    args = parser.parse_args(argv)
    task["handler"](args)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Available tasks:")
        for name in sorted(TASKS.keys()):
            print(f"  {name}")
        return
    run_task(argv[0], argv[1:])


def _add_common_path_arg(parser, default="."):
    parser.add_argument("--path", default=default, help="Path to a file or folder")


def _add_common_recursive_arg(parser, default=True):
    parser.add_argument(
        "--recursive",
        action="store_true" if not default else "store_false",
        help="Toggle recursive scan",
    )


def _add_common_pattern_arg(parser, default="*"):
    parser.add_argument("--pattern", default=default, help="Glob pattern for files")


def _add_recursive_flag(parser):
    parser.add_argument("--no-recursive", action="store_true", help="Do not scan recursively")


def _is_recursive(args):
    return not getattr(args, "no_recursive", False)


def _filter_by_pattern(files, pattern):
    if not pattern or pattern == "*":
        return list(files)
    return [f for f in files if f.match(pattern)]


def _iter_files_with_pattern(path, pattern, recursive=True):
    files = _iter_files(path, recursive=recursive)
    return _filter_by_pattern(files, pattern)


def _safe_relpath(path, base):
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _load_lines(path):
    return [line.strip() for line in _read_text(path).splitlines() if line.strip()]


def _now_stamp(fmt="%Y%m%d_%H%M%S"):
    return dt.datetime.now().strftime(fmt)


def _print_header(title):
    print(title)
    print("-" * len(title))


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _load_json(path):
    return json.loads(_read_text(path))


def _save_json(path, data):
    _write_text(path, json.dumps(data, indent=2, ensure_ascii=True))


def _print_table(rows, headers):
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(str(v))) for w, v in zip(widths, row)]
    fmt = "  ".join([f"{{:<{w}}}" for w in widths])
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*row))


def add_args_directory_size_report(p):
    _add_common_path_arg(p)
    p.add_argument("--top", type=int, default=0, help="Show only top N folders")


def run_directory_size_report(args):
    base = _p(args.path)
    if not base.exists():
        raise SystemExit("Path not found")
    sizes = {}
    for root, _, files in os.walk(base):
        root_path = pathlib.Path(root)
        try:
            rel = root_path.relative_to(base)
        except ValueError:
            rel = pathlib.Path(".")
        key = rel.parts[0] if rel.parts else "."
        for name in files:
            try:
                size = (root_path / name).stat().st_size
            except OSError:
                continue
            sizes[key] = sizes.get(key, 0) + size
    rows = sorted(sizes.items(), key=lambda x: x[1], reverse=True)
    if args.top > 0:
        rows = rows[: args.top]
    for name, size in rows:
        print(f"{name}\t{_format_bytes(size)}")


def add_args_top_largest_files(p):
    _add_common_path_arg(p)
    p.add_argument("--top", type=int, default=20, help="Number of files to show")
    p.add_argument("--min-size", type=int, default=0, help="Minimum size in bytes")
    _add_recursive_flag(p)


def run_top_largest_files(args):
    files = []
    for path in _iter_files(args.path, recursive=_is_recursive(args)):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size >= args.min_size:
            files.append((size, path))
    files.sort(reverse=True, key=lambda x: x[0])
    for size, path in files[: args.top]:
        print(f"{_format_bytes(size)}\t{path}")


def add_args_file_extension_counter(p):
    _add_common_path_arg(p)
    _add_recursive_flag(p)


def run_file_extension_counter(args):
    counts = {}
    for path in _iter_files(args.path, recursive=_is_recursive(args)):
        ext = path.suffix.lower() or "<none>"
        counts[ext] = counts.get(ext, 0) + 1
    rows = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    for ext, count in rows:
        print(f"{ext}\t{count}")


def add_args_move_files_by_extension(p):
    _add_common_path_arg(p)
    p.add_argument("--dry-run", action="store_true", help="Show changes without moving")
    _add_recursive_flag(p)


def run_move_files_by_extension(args):
    base = _p(args.path)
    for path in _iter_files(base, recursive=_is_recursive(args)):
        ext = path.suffix.lower().lstrip(".") or "no_ext"
        dest_dir = base / ext
        dest_path = dest_dir / path.name
        if args.dry_run:
            print(f"Would move: {path} -> {dest_path}")
            continue
        _ensure_dir(dest_dir)
        try:
            shutil.move(str(path), str(dest_path))
            print(f"Moved: {path} -> {dest_path}")
        except OSError as e:
            print(f"Failed: {path} ({e})")


def add_args_rename_extensions(p):
    _add_common_path_arg(p)
    p.add_argument("--old", required=True, help="Old extension, e.g. .txt")
    p.add_argument("--new", required=True, help="New extension, e.g. .md")
    _add_recursive_flag(p)


def run_rename_extensions(args):
    old = args.old if args.old.startswith(".") else "." + args.old
    new = args.new if args.new.startswith(".") else "." + args.new
    for path in _iter_files(args.path, recursive=_is_recursive(args)):
        if path.suffix.lower() != old.lower():
            continue
        dest = path.with_suffix(new)
        try:
            path.rename(dest)
            print(f"Renamed: {path} -> {dest}")
        except OSError as e:
            print(f"Failed: {path} ({e})")


def add_args_remove_empty_dirs(p):
    _add_common_path_arg(p)
    p.add_argument("--dry-run", action="store_true", help="Show changes without deleting")


def run_remove_empty_dirs(args):
    base = _p(args.path)
    if not base.exists():
        raise SystemExit("Path not found")
    removed = 0
    for root, dirs, files in os.walk(base, topdown=False):
        if dirs or files:
            continue
        path = pathlib.Path(root)
        if args.dry_run:
            print(f"Would remove: {path}")
            continue
        try:
            path.rmdir()
            removed += 1
            print(f"Removed: {path}")
        except OSError:
            pass
    print(f"Removed {removed} empty folders")


def add_args_archive_folder_to_zip(p):
    p.add_argument("--source", required=True, help="Folder to archive")
    p.add_argument("--dest", default="", help="Zip path (default: <source>.zip)")


def run_archive_folder_to_zip(args):
    source = _p(args.source)
    if not source.exists():
        raise SystemExit("Source not found")
    dest = _p(args.dest) if args.dest else source.with_suffix(".zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in _iter_files(source, recursive=True):
            zf.write(path, arcname=_safe_relpath(path, source))
    print(f"Created: {dest}")


def add_args_extract_zip_here(p):
    p.add_argument("--zip", required=True, help="Zip file to extract")
    p.add_argument("--dest", default=".", help="Destination folder")


def run_extract_zip_here(args):
    zip_path = _p(args.zip)
    dest = _p(args.dest)
    if not zip_path.exists():
        raise SystemExit("Zip not found")
    _ensure_dir(dest)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)
    print(f"Extracted to: {dest}")


def add_args_backup_directory(p):
    p.add_argument("--source", required=True, help="Folder to back up")
    p.add_argument("--dest", default="backups", help="Backup root folder")


def run_backup_directory(args):
    source = _p(args.source)
    if not source.exists():
        raise SystemExit("Source not found")
    dest_root = _p(args.dest)
    _ensure_dir(dest_root)
    stamp = _now_stamp()
    dest = dest_root / f"{source.name}_{stamp}"
    shutil.copytree(source, dest)
    print(f"Backup created: {dest}")


def add_args_sync_directories(p):
    p.add_argument("--source", required=True, help="Source folder")
    p.add_argument("--dest", required=True, help="Destination folder")
    p.add_argument("--dry-run", action="store_true", help="Show changes without copying")


def run_sync_directories(args):
    source = _p(args.source)
    dest = _p(args.dest)
    if not source.exists():
        raise SystemExit("Source not found")
    _ensure_dir(dest)
    copied = 0
    for path in _iter_files(source, recursive=True):
        rel = path.relative_to(source)
        target = dest / rel
        try:
            src_mtime = path.stat().st_mtime
            dst_mtime = target.stat().st_mtime if target.exists() else -1
        except OSError:
            continue
        if not target.exists() or src_mtime > dst_mtime:
            if args.dry_run:
                print(f"Would copy: {path} -> {target}")
            else:
                _ensure_dir(target.parent)
                shutil.copy2(path, target)
                print(f"Copied: {path} -> {target}")
            copied += 1
    print(f"Files copied: {copied}")


def add_args_old_files_cleaner(p):
    _add_common_path_arg(p)
    p.add_argument("--days", type=int, default=30, help="Delete files older than N days")
    p.add_argument("--apply", action="store_true", help="Delete files (default: dry-run)")
    _add_recursive_flag(p)


def run_old_files_cleaner(args):
    cutoff = time.time() - (args.days * 86400)
    for path in _iter_files(args.path, recursive=_is_recursive(args)):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            if args.apply:
                try:
                    path.unlink()
                    print(f"Deleted: {path}")
                except OSError as e:
                    print(f"Failed: {path} ({e})")
            else:
                print(f"Would delete: {path}")


def add_args_duplicate_file_finder(p):
    _add_common_path_arg(p)
    _add_recursive_flag(p)


def run_duplicate_file_finder(args):
    size_map = {}
    for path in _iter_files(args.path, recursive=_is_recursive(args)):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        size_map.setdefault(size, []).append(path)
    duplicates = []
    for size, paths in size_map.items():
        if len(paths) < 2:
            continue
        hash_map = {}
        for path in paths:
            try:
                h = _hash_file(path)
            except OSError:
                continue
            hash_map.setdefault(h, []).append(path)
        for h, group in hash_map.items():
            if len(group) > 1:
                duplicates.append((size, h, group))
    if not duplicates:
        print("No duplicates found")
        return
    for size, h, group in duplicates:
        print(f"Size {_format_bytes(size)} Hash {h}")
        for path in group:
            print(f"  {path}")


def add_args_hash_file(p):
    _add_common_path_arg(p, default="")
    p.add_argument("--algo", default="sha256", help="Hash algorithm")


def run_hash_file(args):
    if not args.path:
        raise SystemExit("Provide --path")
    print(_hash_file(args.path, algo=args.algo))


def add_args_verify_file_hash(p):
    _add_common_path_arg(p, default="")
    p.add_argument("--expected", required=True, help="Expected hash")
    p.add_argument("--algo", default="sha256", help="Hash algorithm")


def run_verify_file_hash(args):
    if not args.path:
        raise SystemExit("Provide --path")
    actual = _hash_file(args.path, algo=args.algo)
    if actual.lower() == args.expected.lower():
        print("Hash matches")
        return
    print("Hash does not match")
    print(f"Expected: {args.expected}")
    print(f"Actual:   {actual}")
    raise SystemExit(1)


def add_args_generate_password(p):
    p.add_argument("--length", type=int, default=16, help="Password length")
    p.add_argument("--count", type=int, default=1, help="Number of passwords")
    p.add_argument("--no-symbols", action="store_true", help="Exclude symbols")


def run_generate_password(args):
    chars = string.ascii_letters + string.digits
    if not args.no_symbols:
        chars += "!@#$%^&*()-_=+[]{}"
    rng = random.SystemRandom()
    for _ in range(args.count):
        print("".join(rng.choice(chars) for _ in range(args.length)))


def add_args_base64_encode_file(p):
    p.add_argument("--input", required=True, help="Input file")
    p.add_argument("--output", default="", help="Output .b64 file")


def run_base64_encode_file(args):
    inp = _p(args.input)
    out = _p(args.output) if args.output else inp.with_suffix(inp.suffix + ".b64")
    data = inp.read_bytes()
    out.write_bytes(base64.b64encode(data))
    print(f"Wrote: {out}")


def add_args_base64_decode_file(p):
    p.add_argument("--input", required=True, help="Input .b64 file")
    p.add_argument("--output", default="", help="Output file")


def run_base64_decode_file(args):
    inp = _p(args.input)
    out = _p(args.output) if args.output else inp.with_suffix("")
    data = inp.read_bytes()
    out.write_bytes(base64.b64decode(data))
    print(f"Wrote: {out}")


def add_args_text_file_merger(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*.txt")
    p.add_argument("--output", required=True, help="Merged output file")
    _add_recursive_flag(p)


def run_text_file_merger(args):
    output = _p(args.output)
    parts = []
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        parts.append(_read_text(path))
    _write_text(output, "\n".join(parts))
    print(f"Wrote: {output}")


def add_args_search_in_files(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*.txt")
    p.add_argument("--text", required=True, help="Text to search for")
    p.add_argument("--ignore-case", action="store_true", help="Case-insensitive search")
    _add_recursive_flag(p)


def run_search_in_files(args):
    needle = args.text.lower() if args.ignore_case else args.text
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        try:
            lines = _read_text(path).splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, start=1):
            hay = line.lower() if args.ignore_case else line
            if needle in hay:
                print(f"{path}:{i}: {line}")


def add_args_replace_in_files(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*.txt")
    p.add_argument("--old", required=True, help="Text to replace")
    p.add_argument("--new", required=True, help="Replacement text")
    p.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    _add_recursive_flag(p)


def run_replace_in_files(args):
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        try:
            text = _read_text(path)
        except OSError:
            continue
        if args.old not in text:
            continue
        new_text = text.replace(args.old, args.new)
        if args.dry_run:
            print(f"Would update: {path}")
        else:
            _write_text(path, new_text)
            print(f"Updated: {path}")


def add_args_count_lines(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*.txt")
    _add_recursive_flag(p)


def run_count_lines(args):
    total = 0
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        try:
            count = len(_read_text(path).splitlines())
        except OSError:
            continue
        total += count
        print(f"{path}\t{count}")
    print(f"Total lines: {total}")


def add_args_extract_emails(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*.txt")
    p.add_argument("--output", default="", help="Write results to file")
    _add_recursive_flag(p)


def run_extract_emails(args):
    pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    found = set()
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        text = _read_text(path)
        for email in pattern.findall(text):
            found.add(email)
    results = "\n".join(sorted(found))
    if args.output:
        _write_text(args.output, results + ("\n" if results else ""))
        print(f"Wrote: {args.output}")
    else:
        print(results)


def add_args_csv_to_json(p):
    p.add_argument("--input", required=True, help="Input CSV file")
    p.add_argument("--output", required=True, help="Output JSON file")


def run_csv_to_json(args):
    rows = _read_csv(args.input)
    _save_json(args.output, rows)
    print(f"Wrote: {args.output}")


def add_args_json_to_csv(p):
    p.add_argument("--input", required=True, help="Input JSON file")
    p.add_argument("--output", required=True, help="Output CSV file")


def run_json_to_csv(args):
    data = _load_json(args.input)
    if not isinstance(data, list):
        raise SystemExit("JSON must be a list of objects")
    fieldnames = sorted({k for row in data for k in row.keys()})
    _write_csv(args.output, data, fieldnames)
    print(f"Wrote: {args.output}")


def add_args_csv_summary(p):
    p.add_argument("--input", required=True, help="Input CSV file")


def run_csv_summary(args):
    rows = _read_csv(args.input)
    if not rows:
        print("No rows found")
        return
    headers = list(rows[0].keys())
    _print_header("CSV Summary")
    print(f"Rows: {len(rows)}")
    print(f"Columns: {', '.join(headers)}")


def add_args_split_csv(p):
    p.add_argument("--input", required=True, help="Input CSV file")
    p.add_argument("--rows", type=int, default=1000, help="Rows per output file")
    p.add_argument("--output-dir", default="splits", help="Output folder")


def run_split_csv(args):
    rows = _read_csv(args.input)
    if not rows:
        print("No rows to split")
        return
    _ensure_dir(args.output_dir)
    fieldnames = list(rows[0].keys())
    chunk = []
    index = 1
    for row in rows:
        chunk.append(row)
        if len(chunk) >= args.rows:
            out = _p(args.output_dir) / f"part_{index}.csv"
            _write_csv(out, chunk, fieldnames)
            print(f"Wrote: {out}")
            index += 1
            chunk = []
    if chunk:
        out = _p(args.output_dir) / f"part_{index}.csv"
        _write_csv(out, chunk, fieldnames)
        print(f"Wrote: {out}")


def add_args_json_pretty_print(p):
    p.add_argument("--input", required=True, help="Input JSON file")
    p.add_argument("--output", default="", help="Optional output file")


def run_json_pretty_print(args):
    data = _load_json(args.input)
    text = json.dumps(data, indent=2, ensure_ascii=True)
    if args.output:
        _write_text(args.output, text + "\n")
        print(f"Wrote: {args.output}")
    else:
        print(text)


def add_args_validate_json(p):
    p.add_argument("--input", required=True, help="Input JSON file")


def run_validate_json(args):
    try:
        _load_json(args.input)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}")
        raise SystemExit(1)
    print("Valid JSON")


def add_args_csv_column_extractor(p):
    p.add_argument("--input", required=True, help="Input CSV file")
    p.add_argument("--columns", required=True, help="Comma-separated column names")
    p.add_argument("--output", required=True, help="Output CSV file")


def run_csv_column_extractor(args):
    rows = _read_csv(args.input)
    cols = [c.strip() for c in args.columns.split(",") if c.strip()]
    result = [{c: row.get(c, "") for c in cols} for row in rows]
    _write_csv(args.output, result, cols)
    print(f"Wrote: {args.output}")


def add_args_csv_column_renamer(p):
    p.add_argument("--input", required=True, help="Input CSV file")
    p.add_argument("--mapping", required=True, help="Mappings old:new,old2:new2")
    p.add_argument("--output", required=True, help="Output CSV file")


def run_csv_column_renamer(args):
    rows = _read_csv(args.input)
    mapping = {}
    for pair in args.mapping.split(","):
        if ":" in pair:
            old, new = pair.split(":", 1)
            mapping[old.strip()] = new.strip()
    new_rows = []
    for row in rows:
        new_row = {}
        for k, v in row.items():
            new_row[mapping.get(k, k)] = v
        new_rows.append(new_row)
    fieldnames = list(new_rows[0].keys()) if new_rows else []
    _write_csv(args.output, new_rows, fieldnames)
    print(f"Wrote: {args.output}")


def add_args_csv_filter_rows(p):
    p.add_argument("--input", required=True, help="Input CSV file")
    p.add_argument("--column", required=True, help="Column name to filter")
    p.add_argument("--contains", required=True, help="Substring to match")
    p.add_argument("--output", required=True, help="Output CSV file")


def run_csv_filter_rows(args):
    rows = _read_csv(args.input)
    result = [row for row in rows if args.contains in row.get(args.column, "")]
    fieldnames = list(rows[0].keys()) if rows else []
    _write_csv(args.output, result, fieldnames)
    print(f"Wrote: {args.output}")


def add_args_csv_join(p):
    p.add_argument("--left", required=True, help="Left CSV file")
    p.add_argument("--right", required=True, help="Right CSV file")
    p.add_argument("--key", required=True, help="Join key column")
    p.add_argument("--output", required=True, help="Output CSV file")


def run_csv_join(args):
    left = _read_csv(args.left)
    right = _read_csv(args.right)
    right_map = {row.get(args.key): row for row in right}
    result = []
    for row in left:
        joined = dict(row)
        other = right_map.get(row.get(args.key), {})
        for k, v in other.items():
            if k == args.key:
                continue
            joined[k] = v
        result.append(joined)
    fieldnames = sorted({k for r in result for k in r.keys()})
    _write_csv(args.output, result, fieldnames)
    print(f"Wrote: {args.output}")


def add_args_json_merge(p):
    p.add_argument("--left", required=True, help="Left JSON file")
    p.add_argument("--right", required=True, help="Right JSON file")
    p.add_argument("--output", required=True, help="Output JSON file")


def run_json_merge(args):
    left = _load_json(args.left)
    right = _load_json(args.right)
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise SystemExit("JSON files must be objects")
    merged = dict(left)
    merged.update(right)
    _save_json(args.output, merged)
    print(f"Wrote: {args.output}")


def add_args_json_key_finder(p):
    p.add_argument("--input", required=True, help="Input JSON file")
    p.add_argument("--key", required=True, help="Key to find")


def run_json_key_finder(args):
    data = _load_json(args.input)
    matches = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                new_path = f"{path}.{k}" if path else k
                if k == args.key:
                    matches.append(new_path)
                walk(v, new_path)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(data, "")
    if matches:
        print("\n".join(matches))
    else:
        print("No matches found")


def add_args_create_checksum_manifest(p):
    _add_common_path_arg(p)
    p.add_argument("--output", default="checksums.sha256", help="Manifest file")
    _add_recursive_flag(p)


def run_create_checksum_manifest(args):
    base = _p(args.path)
    lines = []
    for path in _iter_files(base, recursive=_is_recursive(args)):
        if path.name == args.output:
            continue
        try:
            h = _hash_file(path)
        except OSError:
            continue
        rel = _safe_relpath(path, base)
        lines.append(f"{h}  {rel}")
    _write_text(args.output, "\n".join(lines) + ("\n" if lines else ""))
    print(f"Wrote: {args.output}")


def add_args_verify_checksum_manifest(p):
    p.add_argument("--manifest", default="checksums.sha256", help="Manifest file")
    p.add_argument("--base", default=".", help="Base folder for relative paths")


def run_verify_checksum_manifest(args):
    base = _p(args.base)
    manifest = _p(args.manifest)
    if not manifest.exists():
        raise SystemExit("Manifest not found")
    ok = True
    for line in _read_text(manifest).splitlines():
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            continue
        expected, rel = parts
        path = base / rel
        if not path.exists():
            print(f"Missing: {rel}")
            ok = False
            continue
        actual = _hash_file(path)
        if actual != expected:
            print(f"Mismatch: {rel}")
            ok = False
    if ok:
        print("All files verified")
    else:
        raise SystemExit(1)


def add_args_compare_csv_files(p):
    p.add_argument("--left", required=True, help="Left CSV file")
    p.add_argument("--right", required=True, help="Right CSV file")
    p.add_argument("--key", required=True, help="Key column")


def run_compare_csv_files(args):
    left = {row.get(args.key): row for row in _read_csv(args.left)}
    right = {row.get(args.key): row for row in _read_csv(args.right)}
    left_keys = set(left.keys())
    right_keys = set(right.keys())
    added = right_keys - left_keys
    removed = left_keys - right_keys
    common = left_keys & right_keys
    changed = []
    for k in common:
        if left[k] != right[k]:
            changed.append(k)
    print(f"Added: {len(added)}")
    for k in sorted(added):
        print(f"  {k}")
    print(f"Removed: {len(removed)}")
    for k in sorted(removed):
        print(f"  {k}")
    print(f"Changed: {len(changed)}")
    for k in sorted(changed):
        print(f"  {k}")


def add_args_http_status_check(p):
    p.add_argument("urls", nargs="*", help="URLs to check")
    p.add_argument("--file", default="", help="File with URLs (one per line)")
    p.add_argument("--timeout", type=int, default=10, help="Timeout in seconds")


def run_http_status_check(args):
    urls = list(args.urls)
    if args.file:
        urls.extend(_load_lines(args.file))
    if not urls:
        raise SystemExit("Provide URLs or --file")
    for url in urls:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                print(f"{url}\t{resp.status}")
        except Exception:
            try:
                with urllib.request.urlopen(url, timeout=args.timeout) as resp:
                    print(f"{url}\t{resp.status}")
            except Exception as e:
                print(f"{url}\tERROR ({e})")


def add_args_download_file(p):
    p.add_argument("--url", required=True, help="URL to download")
    p.add_argument("--output", required=True, help="Output file")


def run_download_file(args):
    with urllib.request.urlopen(args.url) as resp:
        data = resp.read()
    _p(args.output).write_bytes(data)
    print(f"Wrote: {args.output}")


def add_args_ping_hosts(p):
    p.add_argument("hosts", nargs="*", help="Hosts to ping")
    p.add_argument("--file", default="", help="File with hosts")


def run_ping_hosts(args):
    hosts = list(args.hosts)
    if args.file:
        hosts.extend(_load_lines(args.file))
    if not hosts:
        raise SystemExit("Provide hosts or --file")
    for host in hosts:
        result = subprocess.run(
            ["ping", "-n", "1", host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        status = "OK" if result.returncode == 0 else "FAIL"
        print(f"{host}\t{status}")


def add_args_check_port(p):
    p.add_argument("--host", required=True, help="Host to connect to")
    p.add_argument("--port", type=int, required=True, help="Port number")
    p.add_argument("--timeout", type=int, default=3, help="Timeout in seconds")


def run_check_port(args):
    s = socket.socket()
    s.settimeout(args.timeout)
    try:
        s.connect((args.host, args.port))
        print("OPEN")
    except OSError:
        print("CLOSED")
        raise SystemExit(1)
    finally:
        s.close()


def add_args_resolve_dns(p):
    p.add_argument("--host", required=True, help="Hostname to resolve")


def run_resolve_dns(args):
    infos = socket.getaddrinfo(args.host, None)
    addrs = sorted({info[4][0] for info in infos})
    for addr in addrs:
        print(addr)


def add_args_public_ip(p):
    p.add_argument("--url", default="https://api.ipify.org", help="Service URL")


def run_public_ip(args):
    with urllib.request.urlopen(args.url) as resp:
        print(resp.read().decode("utf-8", "ignore"))


def add_args_local_ip(p):
    p.add_argument("--host", default="8.8.8.8", help="Remote host to probe")
    p.add_argument("--port", type=int, default=80, help="Remote port")


def run_local_ip(args):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((args.host, args.port))
        print(s.getsockname()[0])
    finally:
        s.close()


def add_args_disk_usage_report(p):
    _add_common_path_arg(p, default=".")


def run_disk_usage_report(args):
    total, used, free = shutil.disk_usage(_p(args.path))
    _print_kv("Total", _format_bytes(total))
    _print_kv("Used", _format_bytes(used))
    _print_kv("Free", _format_bytes(free))


def add_args_system_info(p):
    pass


def run_system_info(args):
    _print_kv("Platform", sys.platform)
    _print_kv("Python", sys.version.split()[0])
    _print_kv("CWD", os.getcwd())
    _print_kv("User", os.environ.get("USERNAME", ""))
    _print_kv("Hostname", socket.gethostname())
    _print_kv("CPU Count", os.cpu_count())


def add_args_environment_dump(p):
    p.add_argument("--output", default="", help="Output file")


def run_environment_dump(args):
    lines = [f"{k}={v}" for k, v in sorted(os.environ.items())]
    text = "\n".join(lines)
    if args.output:
        _write_text(args.output, text + "\n")
        print(f"Wrote: {args.output}")
    else:
        print(text)


def add_args_list_processes(p):
    pass


def run_list_processes(args):
    result = subprocess.run(["tasklist"], capture_output=True, text=True)
    print(result.stdout)


def add_args_process_info(p):
    p.add_argument("--name", required=True, help="Process name, e.g. python.exe")


def run_process_info(args):
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {args.name}"],
        capture_output=True,
        text=True,
    )
    print(result.stdout)


def add_args_open_url_in_browser(p):
    p.add_argument("--url", required=True, help="URL to open")


def run_open_url_in_browser(args):
    webbrowser.open(args.url)
    print(f"Opened: {args.url}")


def add_args_create_timestamped_folder(p):
    p.add_argument("--base", default=".", help="Base directory")
    p.add_argument("--prefix", default="folder", help="Folder prefix")


def run_create_timestamped_folder(args):
    base = _p(args.base)
    _ensure_dir(base)
    name = f"{args.prefix}_{_now_stamp()}"
    dest = base / name
    _ensure_dir(dest)
    print(f"Created: {dest}")


def add_args_rename_files_with_timestamp(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*")
    p.add_argument("--position", choices=["prefix", "suffix"], default="suffix")
    p.add_argument("--format", default="%Y%m%d_%H%M%S", help="Timestamp format")
    _add_recursive_flag(p)


def run_rename_files_with_timestamp(args):
    stamp = dt.datetime.now().strftime(args.format)
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        new_name = (
            f"{stamp}_{path.name}" if args.position == "prefix" else f"{path.stem}_{stamp}{path.suffix}"
        )
        dest = path.with_name(new_name)
        try:
            path.rename(dest)
            print(f"Renamed: {path} -> {dest}")
        except OSError as e:
            print(f"Failed: {path} ({e})")


def add_args_generate_file_tree(p):
    _add_common_path_arg(p)
    p.add_argument("--output", default="", help="Write tree to file")


def run_generate_file_tree(args):
    base = _p(args.path)
    lines = []
    for root, dirs, files in os.walk(base):
        depth = len(pathlib.Path(root).relative_to(base).parts)
        indent = "  " * depth
        lines.append(f"{indent}{pathlib.Path(root).name}/")
        for name in files:
            lines.append(f"{indent}  {name}")
    text = "\n".join(lines)
    if args.output:
        _write_text(args.output, text + "\n")
        print(f"Wrote: {args.output}")
    else:
        print(text)


def add_args_compare_two_files(p):
    p.add_argument("--left", required=True, help="Left file")
    p.add_argument("--right", required=True, help="Right file")
    p.add_argument("--shallow", action="store_true", help="Shallow compare only")


def run_compare_two_files(args):
    same = filecmp.cmp(args.left, args.right, shallow=args.shallow)
    print("Same" if same else "Different")


def add_args_compare_two_folders(p):
    p.add_argument("--left", required=True, help="Left folder")
    p.add_argument("--right", required=True, help="Right folder")


def run_compare_two_folders(args):
    cmp = filecmp.dircmp(args.left, args.right)
    print("Left only:", cmp.left_only)
    print("Right only:", cmp.right_only)
    print("Diff files:", cmp.diff_files)


def add_args_convert_newlines(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*.txt")
    p.add_argument("--style", choices=["lf", "crlf"], default="lf")
    _add_recursive_flag(p)


def run_convert_newlines(args):
    newline = "\n" if args.style == "lf" else "\r\n"
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        text = _read_text(path)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = newline.join(text.split("\n"))
        _write_text(path, text)
        print(f"Updated: {path}")


def add_args_trim_whitespace(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*.txt")
    _add_recursive_flag(p)


def run_trim_whitespace(args):
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        lines = _read_text(path).splitlines()
        trimmed = [line.rstrip() for line in lines]
        _write_text(path, "\n".join(trimmed) + ("\n" if lines else ""))
        print(f"Updated: {path}")


def add_args_remove_duplicate_lines(p):
    p.add_argument("--input", required=True, help="Input text file")
    p.add_argument("--output", required=True, help="Output file")


def run_remove_duplicate_lines(args):
    seen = set()
    out_lines = []
    for line in _read_text(args.input).splitlines():
        if line in seen:
            continue
        seen.add(line)
        out_lines.append(line)
    _write_text(args.output, "\n".join(out_lines) + ("\n" if out_lines else ""))
    print(f"Wrote: {args.output}")


def add_args_sort_lines(p):
    p.add_argument("--input", required=True, help="Input text file")
    p.add_argument("--output", required=True, help="Output file")
    p.add_argument("--unique", action="store_true", help="Remove duplicates")


def run_sort_lines(args):
    lines = _read_text(args.input).splitlines()
    if args.unique:
        lines = sorted(set(lines))
    else:
        lines = sorted(lines)
    _write_text(args.output, "\n".join(lines) + ("\n" if lines else ""))
    print(f"Wrote: {args.output}")


def add_args_unique_words_counter(p):
    p.add_argument("--input", required=True, help="Input text file")


def run_unique_words_counter(args):
    text = _read_text(args.input)
    words = re.findall(r"[A-Za-z0-9']+", text.lower())
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    rows = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    for word, count in rows[:50]:
        print(f"{word}\t{count}")


def add_args_log_rotate(p):
    p.add_argument("--path", required=True, help="Log file")
    p.add_argument("--keep", type=int, default=5, help="Number of backups")


def run_log_rotate(args):
    path = _p(args.path)
    if not path.exists():
        raise SystemExit("Log file not found")
    for i in range(args.keep, 0, -1):
        older = path.with_suffix(path.suffix + f".{i}")
        newer = path.with_suffix(path.suffix + f".{i + 1}")
        if older.exists():
            if i == args.keep:
                older.unlink(missing_ok=True)
            else:
                older.rename(newer)
    path.rename(path.with_suffix(path.suffix + ".1"))
    path.touch()
    print("Log rotated")


def add_args_append_date_to_filenames(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*")
    _add_recursive_flag(p)


def run_append_date_to_filenames(args):
    stamp = dt.datetime.now().strftime("%Y%m%d")
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        dest = path.with_name(f"{path.stem}_{stamp}{path.suffix}")
        path.rename(dest)
        print(f"Renamed: {path} -> {dest}")


def add_args_remove_date_from_filenames(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*")
    _add_recursive_flag(p)


def run_remove_date_from_filenames(args):
    pattern = re.compile(r"_(\d{8})$")
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        stem = path.stem
        new_stem = pattern.sub("", stem)
        if new_stem != stem:
            dest = path.with_name(new_stem + path.suffix)
            path.rename(dest)
            print(f"Renamed: {path} -> {dest}")


def add_args_create_daily_notes(p):
    p.add_argument("--dir", default="notes", help="Notes folder")


def run_create_daily_notes(args):
    folder = _p(args.dir)
    _ensure_dir(folder)
    name = dt.date.today().isoformat() + ".md"
    path = folder / name
    if not path.exists():
        _write_text(path, f"# {dt.date.today().isoformat()}\n")
        print(f"Created: {path}")
    else:
        print(f"Exists: {path}")


def add_args_create_project_scaffold(p):
    p.add_argument("--path", default=".", help="Base project folder")


def run_create_project_scaffold(args):
    base = _p(args.path)
    for name in ["src", "tests", "docs", "scripts"]:
        _ensure_dir(base / name)
    _write_text(base / "README.md", f"# {base.name}\n")
    print(f"Scaffold created in: {base}")


def add_args_clipboard_save_text(p):
    p.add_argument("--output", required=True, help="Output file")


def run_clipboard_save_text(args):
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        text = root.clipboard_get()
    finally:
        root.destroy()
    _write_text(args.output, text)
    print(f"Wrote: {args.output}")


def add_args_clipboard_load_text(p):
    p.add_argument("--input", required=True, help="Input file")


def run_clipboard_load_text(args):
    import tkinter as tk

    text = _read_text(args.input)
    root = tk.Tk()
    root.withdraw()
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
    finally:
        root.destroy()
    print("Clipboard updated")


def add_args_random_quote_picker(p):
    p.add_argument("--input", required=True, help="Input text file")


def run_random_quote_picker(args):
    lines = [line for line in _read_text(args.input).splitlines() if line.strip()]
    if not lines:
        raise SystemExit("No lines found")
    print(random.choice(lines))


def add_args_url_list_checker(p):
    p.add_argument("--file", required=True, help="File with URLs")
    p.add_argument("--timeout", type=int, default=10, help="Timeout in seconds")


def run_url_list_checker(args):
    urls = _load_lines(args.file)
    for url in urls:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                print(f"{url}\t{resp.status}")
        except Exception:
            try:
                with urllib.request.urlopen(url, timeout=args.timeout) as resp:
                    print(f"{url}\t{resp.status}")
            except Exception as e:
                print(f"{url}\tERROR ({e})")


def add_args_generate_uuids(p):
    p.add_argument("--count", type=int, default=1, help="Number of UUIDs")


def run_generate_uuids(args):
    import uuid

    for _ in range(args.count):
        print(uuid.uuid4())


def add_args_generate_random_data_csv(p):
    p.add_argument("--output", required=True, help="Output CSV file")
    p.add_argument("--rows", type=int, default=100, help="Number of rows")


def run_generate_random_data_csv(args):
    first_names = ["Alex", "Jamie", "Taylor", "Jordan", "Sam", "Riley", "Morgan"]
    last_names = ["Lee", "Patel", "Garcia", "Brown", "Jones", "Kim", "Wong"]
    rng = random.Random()
    rows = []
    for i in range(args.rows):
        first = rng.choice(first_names)
        last = rng.choice(last_names)
        age = rng.randint(18, 70)
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        rows.append({"id": i + 1, "first": first, "last": last, "age": age, "email": email})
    _write_csv(args.output, rows, ["id", "first", "last", "age", "email"])
    print(f"Wrote: {args.output}")


def add_args_rename_by_regex(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*")
    p.add_argument("--regex", required=True, help="Regex pattern")
    p.add_argument("--replace", required=True, help="Replacement")
    _add_recursive_flag(p)


def run_rename_by_regex(args):
    pattern = re.compile(args.regex)
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        new_name = pattern.sub(args.replace, path.name)
        if new_name == path.name:
            continue
        dest = path.with_name(new_name)
        path.rename(dest)
        print(f"Renamed: {path} -> {dest}")


def add_args_change_file_permissions(p):
    _add_common_path_arg(p)
    p.add_argument("--mode", choices=["readonly", "writable"], required=True)
    _add_recursive_flag(p)


def run_change_file_permissions(args):
    read_only = args.mode == "readonly"
    for path in _iter_files(args.path, recursive=_is_recursive(args)):
        try:
            if read_only:
                path.chmod(path.stat().st_mode & ~0o222)
            else:
                path.chmod(path.stat().st_mode | 0o222)
            print(f"Updated: {path}")
        except OSError as e:
            print(f"Failed: {path} ({e})")


def add_args_file_copy_with_progress(p):
    p.add_argument("--source", required=True, help="Source file")
    p.add_argument("--dest", required=True, help="Destination file")


def run_file_copy_with_progress(args):
    src = _p(args.source)
    dst = _p(args.dest)
    total = src.stat().st_size
    copied = 0
    _ensure_dir(dst.parent)
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while True:
            chunk = fsrc.read(1024 * 1024)
            if not chunk:
                break
            fdst.write(chunk)
            copied += len(chunk)
            print(f"\r{copied}/{total} bytes", end="")
    print("\nCopy complete")


def add_args_file_move_with_backup(p):
    p.add_argument("--source", required=True, help="Source file")
    p.add_argument("--dest", required=True, help="Destination file")


def run_file_move_with_backup(args):
    src = _p(args.source)
    dst = _p(args.dest)
    _ensure_dir(dst.parent)
    if dst.exists():
        backup = dst.with_suffix(dst.suffix + f".bak_{_now_stamp()}")
        dst.rename(backup)
        print(f"Backed up: {backup}")
    shutil.move(str(src), str(dst))
    print(f"Moved: {src} -> {dst}")


def add_args_list_installed_python_packages(p):
    pass


def run_list_installed_python_packages(args):
    result = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True)
    print(result.stdout)


def add_args_detect_large_folders(p):
    _add_common_path_arg(p)
    p.add_argument("--top", type=int, default=10, help="Top N folders")


def run_detect_large_folders(args):
    base = _p(args.path)
    sizes = {}
    for root, _, files in os.walk(base):
        root_path = pathlib.Path(root)
        try:
            rel = root_path.relative_to(base)
        except ValueError:
            rel = pathlib.Path(".")
        key = rel.parts[0] if rel.parts else "."
        for name in files:
            try:
                size = (root_path / name).stat().st_size
            except OSError:
                continue
            sizes[key] = sizes.get(key, 0) + size
    rows = sorted(sizes.items(), key=lambda x: x[1], reverse=True)[: args.top]
    for name, size in rows:
        print(f"{name}\t{_format_bytes(size)}")


def add_args_directory_watcher(p):
    _add_common_path_arg(p)
    p.add_argument("--interval", type=int, default=5, help="Poll interval (seconds)")


def run_directory_watcher(args):
    base = _p(args.path)
    snapshot = {str(p): p.stat().st_mtime for p in _iter_files(base, recursive=True)}
    print("Watching for changes. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(args.interval)
            current = {str(p): p.stat().st_mtime for p in _iter_files(base, recursive=True)}
            added = set(current) - set(snapshot)
            removed = set(snapshot) - set(current)
            changed = {p for p in current if p in snapshot and current[p] != snapshot[p]}
            for p in sorted(added):
                print(f"Added: {p}")
            for p in sorted(removed):
                print(f"Removed: {p}")
            for p in sorted(changed):
                print(f"Changed: {p}")
            snapshot = current
    except KeyboardInterrupt:
        print("Stopped")


def add_args_http_server_here(p):
    p.add_argument("--port", type=int, default=8000, help="Port to serve on")


def run_http_server_here(args):
    import http.server
    import socketserver

    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", args.port), handler) as httpd:
        print(f"Serving on http://localhost:{args.port}")
        httpd.serve_forever()


def add_args_simple_scheduler(p):
    p.add_argument("--time", required=True, help="Time in HH:MM (24h)")
    p.add_argument("--command", required=True, help="Command to run")


def run_simple_scheduler(args):
    now = dt.datetime.now()
    hour, minute = [int(x) for x in args.time.split(":")]
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target < now:
        target += dt.timedelta(days=1)
    delay = (target - now).total_seconds()
    print(f"Waiting {int(delay)} seconds...")
    time.sleep(max(0, delay))
    subprocess.run(args.command, shell=True)


def add_args_countdown_timer(p):
    p.add_argument("--seconds", type=int, required=True, help="Seconds to count down")


def run_countdown_timer(args):
    for remaining in range(args.seconds, 0, -1):
        print(f"\r{remaining} ", end="")
        time.sleep(1)
    print("\nDone")


def add_args_stopwatch(p):
    pass


def run_stopwatch(args):
    input("Press Enter to start...")
    start = time.time()
    input("Press Enter to stop...")
    elapsed = time.time() - start
    print(f"Elapsed: {elapsed:.2f} seconds")


def add_args_generate_report_html(p):
    p.add_argument("--input", required=True, help="Input text file")
    p.add_argument("--output", required=True, help="Output HTML file")


def run_generate_report_html(args):
    text = html.escape(_read_text(args.input))
    content = f"<html><body><pre>{text}</pre></body></html>"
    _write_text(args.output, content)
    print(f"Wrote: {args.output}")


def add_args_backup_to_zip_daily(p):
    p.add_argument("--source", required=True, help="Folder to zip")
    p.add_argument("--dest", default="backups", help="Destination folder")


def run_backup_to_zip_daily(args):
    source = _p(args.source)
    _ensure_dir(args.dest)
    stamp = dt.date.today().isoformat()
    dest = _p(args.dest) / f"{source.name}_{stamp}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in _iter_files(source, recursive=True):
            zf.write(path, arcname=_safe_relpath(path, source))
    print(f"Created: {dest}")


def add_args_extract_archive_batch(p):
    _add_common_path_arg(p)


def run_extract_archive_batch(args):
    base = _p(args.path)
    for zip_path in base.glob("*.zip"):
        dest = base / zip_path.stem
        _ensure_dir(dest)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)
        print(f"Extracted: {zip_path} -> {dest}")


def add_args_check_path_length(p):
    _add_common_path_arg(p)
    p.add_argument("--length", type=int, default=240, help="Path length threshold")
    _add_recursive_flag(p)


def run_check_path_length(args):
    for path in _iter_files(args.path, recursive=_is_recursive(args)):
        if len(str(path)) > args.length:
            print(path)


def add_args_detect_non_ascii(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*.txt")
    _add_recursive_flag(p)


def run_detect_non_ascii(args):
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        data = path.read_bytes()
        if any(b > 127 for b in data):
            print(path)


def add_args_convert_tabs_to_spaces(p):
    p.add_argument("--input", required=True, help="Input file")
    p.add_argument("--output", required=True, help="Output file")
    p.add_argument("--spaces", type=int, default=4, help="Spaces per tab")


def run_convert_tabs_to_spaces(args):
    text = _read_text(args.input).replace("\t", " " * args.spaces)
    _write_text(args.output, text)
    print(f"Wrote: {args.output}")


def add_args_convert_spaces_to_tabs(p):
    p.add_argument("--input", required=True, help="Input file")
    p.add_argument("--output", required=True, help="Output file")
    p.add_argument("--spaces", type=int, default=4, help="Spaces per tab")


def run_convert_spaces_to_tabs(args):
    text = _read_text(args.input)
    text = text.replace(" " * args.spaces, "\t")
    _write_text(args.output, text)
    print(f"Wrote: {args.output}")


def add_args_number_files_sequentially(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*")
    _add_recursive_flag(p)


def run_number_files_sequentially(args):
    files = sorted(_iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)))
    width = len(str(len(files)))
    for i, path in enumerate(files, start=1):
        new_name = f"{str(i).zfill(width)}_{path.name}"
        dest = path.with_name(new_name)
        path.rename(dest)
        print(f"Renamed: {path} -> {dest}")


def add_args_undo_numbering_from_prefix(p):
    _add_common_path_arg(p)
    _add_common_pattern_arg(p, default="*")
    _add_recursive_flag(p)


def run_undo_numbering_from_prefix(args):
    pattern = re.compile(r"^\d+_")
    for path in _iter_files_with_pattern(args.path, args.pattern, recursive=_is_recursive(args)):
        new_name = pattern.sub("", path.name)
        if new_name != path.name:
            dest = path.with_name(new_name)
            path.rename(dest)
            print(f"Renamed: {path} -> {dest}")


def add_args_create_env_file_template(p):
    p.add_argument("--output", default=".env", help="Output .env file")
    p.add_argument("--keys", default="", help="Comma-separated keys")
    p.add_argument("--file", default="", help="File with keys")


def run_create_env_file_template(args):
    keys = []
    if args.keys:
        keys.extend([k.strip() for k in args.keys.split(",") if k.strip()])
    if args.file:
        keys.extend(_load_lines(args.file))
    if not keys:
        raise SystemExit("Provide keys via --keys or --file")
    lines = [f"{k}=" for k in keys]
    _write_text(args.output, "\n".join(lines) + "\n")
    print(f"Wrote: {args.output}")


def add_args_validate_env_file(p):
    p.add_argument("--env", default=".env", help="Env file")
    p.add_argument("--keys", default="", help="Comma-separated required keys")
    p.add_argument("--file", default="", help="File with required keys")


def run_validate_env_file(args):
    required = []
    if args.keys:
        required.extend([k.strip() for k in args.keys.split(",") if k.strip()])
    if args.file:
        required.extend(_load_lines(args.file))
    data = {}
    for line in _read_text(args.env).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    missing = [k for k in required if k not in data or data[k] == ""]
    if missing:
        print("Missing:", ", ".join(missing))
        raise SystemExit(1)
    print("All keys present")


def add_args_list_listening_ports(p):
    pass


def run_list_listening_ports(args):
    result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    lines = [line for line in result.stdout.splitlines() if "LISTENING" in line]
    for line in lines:
        print(line.strip())


def add_args_download_webpage_title(p):
    p.add_argument("--url", required=True, help="URL to fetch")


def run_download_webpage_title(args):
    with urllib.request.urlopen(args.url) as resp:
        text = resp.read().decode("utf-8", "ignore")
    match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    if match:
        print(match.group(1).strip())
    else:
        print("Title not found")


def add_args_generate_sitemap_from_folder(p):
    _add_common_path_arg(p)
    p.add_argument("--base-url", required=True, help="Base URL, e.g. https://example.com")
    p.add_argument("--output", default="sitemap.xml", help="Output sitemap file")


def run_generate_sitemap_from_folder(args):
    base = _p(args.path)
    urls = []
    for path in _iter_files(base, recursive=True):
        rel = _safe_relpath(path, base).replace(os.sep, "/")
        urls.append(f"{args.base_url.rstrip('/')}/{rel}")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<urlset>"]
    for url in urls:
        lines.append(f"  <url><loc>{html.escape(url)}</loc></url>")
    lines.append("</urlset>")
    _write_text(args.output, "\n".join(lines) + "\n")
    print(f"Wrote: {args.output}")


def add_args_create_markdown_index(p):
    _add_common_path_arg(p)
    p.add_argument("--output", default="INDEX.md", help="Output markdown file")


def run_create_markdown_index(args):
    base = _p(args.path)
    lines = ["# Index", ""]
    for path in _iter_files(base, recursive=True):
        rel = _safe_relpath(path, base).replace(os.sep, "/")
        lines.append(f"- {rel}")
    _write_text(args.output, "\n".join(lines) + "\n")
    print(f"Wrote: {args.output}")


def add_args_rename_by_mapping_csv(p):
    p.add_argument("--input", required=True, help="CSV with old,new columns")
    p.add_argument("--base", default=".", help="Base folder")


def run_rename_by_mapping_csv(args):
    rows = _read_csv(args.input)
    base = _p(args.base)
    for row in rows:
        old = row.get("old") or row.get("source")
        new = row.get("new") or row.get("dest")
        if not old or not new:
            continue
        src = base / old
        dst = base / new
        if not src.exists():
            print(f"Missing: {src}")
            continue
        _ensure_dir(dst.parent)
        src.rename(dst)
        print(f"Renamed: {src} -> {dst}")


def add_args_find_large_files_by_extension(p):
    _add_common_path_arg(p)
    p.add_argument("--ext", required=True, help="Extension, e.g. .log")
    p.add_argument("--min-size", type=int, default=10 * 1024 * 1024, help="Minimum size")
    _add_recursive_flag(p)


def run_find_large_files_by_extension(args):
    ext = args.ext if args.ext.startswith(".") else "." + args.ext
    for path in _iter_files(args.path, recursive=_is_recursive(args)):
        if path.suffix.lower() != ext.lower():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size >= args.min_size:
            print(f"{_format_bytes(size)}\t{path}")


def register_tasks():
    tasks = [
        ("directory_size_report", "Report folder sizes", add_args_directory_size_report, run_directory_size_report),
        ("top_largest_files", "List largest files", add_args_top_largest_files, run_top_largest_files),
        ("file_extension_counter", "Count files by extension", add_args_file_extension_counter, run_file_extension_counter),
        ("move_files_by_extension", "Move files into extension folders", add_args_move_files_by_extension, run_move_files_by_extension),
        ("rename_extensions", "Rename file extensions", add_args_rename_extensions, run_rename_extensions),
        ("remove_empty_dirs", "Remove empty directories", add_args_remove_empty_dirs, run_remove_empty_dirs),
        ("archive_folder_to_zip", "Archive a folder to zip", add_args_archive_folder_to_zip, run_archive_folder_to_zip),
        ("extract_zip_here", "Extract a zip file", add_args_extract_zip_here, run_extract_zip_here),
        ("backup_directory", "Backup a directory", add_args_backup_directory, run_backup_directory),
        ("sync_directories", "Sync directories (one-way)", add_args_sync_directories, run_sync_directories),
        ("old_files_cleaner", "Clean old files", add_args_old_files_cleaner, run_old_files_cleaner),
        ("duplicate_file_finder", "Find duplicate files", add_args_duplicate_file_finder, run_duplicate_file_finder),
        ("hash_file", "Compute file hash", add_args_hash_file, run_hash_file),
        ("verify_file_hash", "Verify file hash", add_args_verify_file_hash, run_verify_file_hash),
        ("generate_password", "Generate random passwords", add_args_generate_password, run_generate_password),
        ("base64_encode_file", "Base64 encode a file", add_args_base64_encode_file, run_base64_encode_file),
        ("base64_decode_file", "Base64 decode a file", add_args_base64_decode_file, run_base64_decode_file),
        ("text_file_merger", "Merge text files", add_args_text_file_merger, run_text_file_merger),
        ("search_in_files", "Search text in files", add_args_search_in_files, run_search_in_files),
        ("replace_in_files", "Replace text in files", add_args_replace_in_files, run_replace_in_files),
        ("count_lines", "Count lines in files", add_args_count_lines, run_count_lines),
        ("extract_emails", "Extract emails from files", add_args_extract_emails, run_extract_emails),
        ("csv_to_json", "Convert CSV to JSON", add_args_csv_to_json, run_csv_to_json),
        ("json_to_csv", "Convert JSON to CSV", add_args_json_to_csv, run_json_to_csv),
        ("csv_summary", "Show CSV summary", add_args_csv_summary, run_csv_summary),
        ("split_csv", "Split CSV into parts", add_args_split_csv, run_split_csv),
        ("json_pretty_print", "Pretty print JSON", add_args_json_pretty_print, run_json_pretty_print),
        ("validate_json", "Validate JSON file", add_args_validate_json, run_validate_json),
        ("http_status_check", "Check HTTP status", add_args_http_status_check, run_http_status_check),
        ("download_file", "Download a file", add_args_download_file, run_download_file),
        ("ping_hosts", "Ping hosts", add_args_ping_hosts, run_ping_hosts),
        ("check_port", "Check TCP port", add_args_check_port, run_check_port),
        ("resolve_dns", "Resolve DNS", add_args_resolve_dns, run_resolve_dns),
        ("public_ip", "Get public IP", add_args_public_ip, run_public_ip),
        ("local_ip", "Get local IP", add_args_local_ip, run_local_ip),
        ("disk_usage_report", "Report disk usage", add_args_disk_usage_report, run_disk_usage_report),
        ("system_info", "Show system info", add_args_system_info, run_system_info),
        ("environment_dump", "Dump environment variables", add_args_environment_dump, run_environment_dump),
        ("list_processes", "List running processes", add_args_list_processes, run_list_processes),
        ("process_info", "Filter process info", add_args_process_info, run_process_info),
        ("open_url_in_browser", "Open a URL in browser", add_args_open_url_in_browser, run_open_url_in_browser),
        ("create_timestamped_folder", "Create timestamped folder", add_args_create_timestamped_folder, run_create_timestamped_folder),
        ("rename_files_with_timestamp", "Rename files with timestamp", add_args_rename_files_with_timestamp, run_rename_files_with_timestamp),
        ("generate_file_tree", "Generate file tree", add_args_generate_file_tree, run_generate_file_tree),
        ("compare_two_files", "Compare two files", add_args_compare_two_files, run_compare_two_files),
        ("compare_two_folders", "Compare two folders", add_args_compare_two_folders, run_compare_two_folders),
        ("convert_newlines", "Convert line endings", add_args_convert_newlines, run_convert_newlines),
        ("trim_whitespace", "Trim trailing whitespace", add_args_trim_whitespace, run_trim_whitespace),
        ("remove_duplicate_lines", "Remove duplicate lines", add_args_remove_duplicate_lines, run_remove_duplicate_lines),
        ("sort_lines", "Sort lines in a file", add_args_sort_lines, run_sort_lines),
        ("unique_words_counter", "Count unique words", add_args_unique_words_counter, run_unique_words_counter),
        ("log_rotate", "Rotate a log file", add_args_log_rotate, run_log_rotate),
        ("append_date_to_filenames", "Append date to filenames", add_args_append_date_to_filenames, run_append_date_to_filenames),
        ("remove_date_from_filenames", "Remove date from filenames", add_args_remove_date_from_filenames, run_remove_date_from_filenames),
        ("create_daily_notes", "Create daily notes file", add_args_create_daily_notes, run_create_daily_notes),
        ("create_project_scaffold", "Create project scaffold", add_args_create_project_scaffold, run_create_project_scaffold),
        ("clipboard_save_text", "Save clipboard to file", add_args_clipboard_save_text, run_clipboard_save_text),
        ("clipboard_load_text", "Load file to clipboard", add_args_clipboard_load_text, run_clipboard_load_text),
        ("random_quote_picker", "Pick random line from file", add_args_random_quote_picker, run_random_quote_picker),
        ("url_list_checker", "Check URLs from file", add_args_url_list_checker, run_url_list_checker),
        ("generate_uuids", "Generate UUIDs", add_args_generate_uuids, run_generate_uuids),
        ("generate_random_data_csv", "Generate sample CSV data", add_args_generate_random_data_csv, run_generate_random_data_csv),
        ("csv_column_extractor", "Extract CSV columns", add_args_csv_column_extractor, run_csv_column_extractor),
        ("csv_column_renamer", "Rename CSV columns", add_args_csv_column_renamer, run_csv_column_renamer),
        ("csv_filter_rows", "Filter CSV rows", add_args_csv_filter_rows, run_csv_filter_rows),
        ("csv_join", "Join two CSV files", add_args_csv_join, run_csv_join),
        ("json_merge", "Merge JSON objects", add_args_json_merge, run_json_merge),
        ("json_key_finder", "Find key in JSON", add_args_json_key_finder, run_json_key_finder),
        ("create_checksum_manifest", "Create checksum manifest", add_args_create_checksum_manifest, run_create_checksum_manifest),
        ("verify_checksum_manifest", "Verify checksum manifest", add_args_verify_checksum_manifest, run_verify_checksum_manifest),
        ("rename_by_regex", "Rename files with regex", add_args_rename_by_regex, run_rename_by_regex),
        ("change_file_permissions", "Change file permissions", add_args_change_file_permissions, run_change_file_permissions),
        ("file_copy_with_progress", "Copy file with progress", add_args_file_copy_with_progress, run_file_copy_with_progress),
        ("file_move_with_backup", "Move file with backup", add_args_file_move_with_backup, run_file_move_with_backup),
        ("list_installed_python_packages", "List installed Python packages", add_args_list_installed_python_packages, run_list_installed_python_packages),
        ("detect_large_folders", "Detect large folders", add_args_detect_large_folders, run_detect_large_folders),
        ("directory_watcher", "Watch a directory for changes", add_args_directory_watcher, run_directory_watcher),
        ("http_server_here", "Start a local HTTP server", add_args_http_server_here, run_http_server_here),
        ("simple_scheduler", "Run a command at a time", add_args_simple_scheduler, run_simple_scheduler),
        ("countdown_timer", "Run a countdown timer", add_args_countdown_timer, run_countdown_timer),
        ("stopwatch", "Run a stopwatch", add_args_stopwatch, run_stopwatch),
        ("generate_report_html", "Generate HTML report", add_args_generate_report_html, run_generate_report_html),
        ("backup_to_zip_daily", "Daily zip backup", add_args_backup_to_zip_daily, run_backup_to_zip_daily),
        ("extract_archive_batch", "Extract all zips in folder", add_args_extract_archive_batch, run_extract_archive_batch),
        ("check_path_length", "Find long paths", add_args_check_path_length, run_check_path_length),
        ("detect_non_ascii", "Detect non-ASCII files", add_args_detect_non_ascii, run_detect_non_ascii),
        ("convert_tabs_to_spaces", "Convert tabs to spaces", add_args_convert_tabs_to_spaces, run_convert_tabs_to_spaces),
        ("convert_spaces_to_tabs", "Convert spaces to tabs", add_args_convert_spaces_to_tabs, run_convert_spaces_to_tabs),
        ("number_files_sequentially", "Number files sequentially", add_args_number_files_sequentially, run_number_files_sequentially),
        ("undo_numbering_from_prefix", "Remove numbering prefix", add_args_undo_numbering_from_prefix, run_undo_numbering_from_prefix),
        ("create_env_file_template", "Create .env template", add_args_create_env_file_template, run_create_env_file_template),
        ("validate_env_file", "Validate .env file", add_args_validate_env_file, run_validate_env_file),
        ("list_listening_ports", "List listening ports", add_args_list_listening_ports, run_list_listening_ports),
        ("download_webpage_title", "Fetch webpage title", add_args_download_webpage_title, run_download_webpage_title),
        ("generate_sitemap_from_folder", "Generate sitemap from folder", add_args_generate_sitemap_from_folder, run_generate_sitemap_from_folder),
        ("create_markdown_index", "Create markdown index", add_args_create_markdown_index, run_create_markdown_index),
        ("compare_csv_files", "Compare CSV files", add_args_compare_csv_files, run_compare_csv_files),
        ("rename_by_mapping_csv", "Rename files from CSV mapping", add_args_rename_by_mapping_csv, run_rename_by_mapping_csv),
        ("find_large_files_by_extension", "Find large files by extension", add_args_find_large_files_by_extension, run_find_large_files_by_extension),
    ]
    for name, desc, add_args, handler in tasks:
        register_task(name, desc, add_args, handler)

register_tasks()


if __name__ == "__main__":
    main()
