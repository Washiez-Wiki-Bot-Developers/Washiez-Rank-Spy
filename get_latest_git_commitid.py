import subprocess,os

def get_latest_commit(file_path, short=False):
    try:
        fmt = '%h' if short else '%H'
        result = subprocess.run(
            ['git', 'log', '-1', f'--pretty=format:{fmt}', '--', file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"

def get_commits_for_files(file_list):
    commits = {}
    for file in file_list:
        full = get_latest_commit(file, short=False)
        short = get_latest_commit(file, short=True)
        commits[file] = {'full': full, 'short': short}
    return commits

def get_items_in_parent_directory_only(directory):
    import os
    items = []
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            items.append(name)
    return items

if __name__ == "__main__":
    # files = ['app.py', 'another_file.py', 'some_folder/third_file.py']  # Add your files here
    # latest_commits = get_commits_for_files(files)
    # for file, commit in latest_commits.items():
    #     print(f"{file}: full={commit['full']} short={commit['short']}")
    
    files = get_items_in_parent_directory_only(os.path.dirname(__file__))
    latest_commits = get_commits_for_files(files)
    for file, commit in latest_commits.items():
        print(f"{file}: full={commit['full']} short={commit['short']}")