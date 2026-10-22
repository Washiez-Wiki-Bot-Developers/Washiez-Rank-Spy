import subprocess
import os
import re
from rich.console import Console

console = Console()

def is_valid_git_hash(hash_str, short=False):
    """Check if the string is a valid git commit hash."""
    if short:
        # Short hashes are usually 7–10 hex chars
        return bool(re.fullmatch(r"[0-9a-f]{7,10}", hash_str))
    else:
        # Full hashes are exactly 40 hex chars
        return bool(re.fullmatch(r"[0-9a-f]{40}", hash_str))

def get_latest_commit(file_path, short=False):
    with console.status("[bold green]Retrieving current git commit...[/]", refresh_per_second=2):
        fmt = '%h' if short else '%H'
        try:
            result = subprocess.run(
                ['git', 'log', '-1', f'--pretty=format:{fmt}', '--', file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            commit_hash = result.stdout.strip()

            # Check if empty or invalid
            if not commit_hash:
                raise RuntimeError(f"No commit found for file: {file_path}")
            if not is_valid_git_hash(commit_hash, short=short):
                raise ValueError(f"Invalid commit hash returned for file '{file_path}': {commit_hash}")

            return commit_hash

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git error for file '{file_path}': {e.stderr.strip()}") from e

def get_latest_tag():
    with console.status("[bold green]Retrieving latest git tag...[/]", refresh_per_second=2):
        try:
            result = subprocess.run(
                ['git', 'describe', '--tags', '--abbrev=0'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            tag = result.stdout.strip()
            return tag
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git error while retrieving latest tag: {e.stderr.strip()}") from e

def get_commits_for_files(file_list):
    commits = {}
    for file in file_list:
        full = get_latest_commit(file, short=False)
        short = get_latest_commit(file, short=True)
        commits[file] = {'full': full, 'short': short}
    return commits

def get_items_in_parent_directory_only(directory):
    items = []
    with console.status("[bold green]Retrieving all items in parent directory of this file...[/]", refresh_per_second=2):
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                items.append(name)
    return items

if __name__ == "__main__":
    files = get_items_in_parent_directory_only(os.path.dirname(__file__))
    latest_commits = get_commits_for_files(files)
    for file, commit in latest_commits.items():
        print(f"{file}: full={commit['full']} short={commit['short']}")
