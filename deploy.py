import subprocess

commit_message = input("Enter a commit message: ").strip()

if not commit_message:
    print("Commit message is required.")
    exit(1)

commands = [
    "git add .",
    f'git commit -m "{commit_message}"',
    "git push heroku master"  # Change to "master" if using that
]

for cmd in commands:
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print("❌ Command failed, stopping.")
        break
