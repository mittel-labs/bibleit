import os
import sys


def gen(target):
    input_file = target
    if not os.path.isfile(input_file):
        input_file = f"../src/bibleit/translations/{arg}"
    if not os.path.isfile(input_file):
        print(f"Error: translation '{input_file}' not found")
        sys.exit(1)

    chapters_file = f"diff.{target}.chapters"
    chapters_count_file = f"diff.{target}.chapters.count"

    print(f"> {target}")

    print("Reading file..")
    with open(input_file, "r") as f:
        lines = f.readlines()

    print("Generating chapters..")
    chapters = set(line.split(":")[0] for line in lines)
    with open(chapters_file, "w") as f:
        f.write("\n".join(chapters))

    print("Generating counting..")
    counts = {}
    for line in lines:
        chapter = line.split(":")[0]
        counts[chapter] = counts.get(chapter, 0) + 1
    with open(chapters_count_file, "w") as f:
        for chapter, count in counts.items():
            f.write(f"{chapter} $ {count}\n")

    print("done")


for arg in sys.argv[1:]:
    # search in pre-defined directory: ../src/bibleit/translations/
    gen(arg)
