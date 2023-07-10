import glob
import re

translation = "NTLH"
bible_files_dir = f"bolls/bibles/{translation}"


def extract_chapter_and_verse(reference_text):
    # Extract book name, chapter, and verse using regular expressions
    pattern = r"^([\w\s]+)\s(\d+):(\d+).*$"
    match = re.match(pattern, reference_text)

    if match:
        book_name = match.group(1)
        chapter = int(match.group(2))
        verse = int(match.group(3))
        return book_name, chapter, verse
    else:
        return None


# Iterate over each text file
for filename in glob.glob(f"{bible_files_dir}/*.txt"):
    new_lines = []
    print(f"Processing {filename}...")
    with open(filename, "r") as f:
        # Read the contents of the file
        content = f.read()

        # Split the content into a list of lines
        lines = content.split("\n")
        prev_chapter = 1
        cur_cnt = 1

        for i, line in enumerate(lines):
            if line == "":
                continue
            book, chapter, verse = extract_chapter_and_verse(line)

            if chapter != prev_chapter:
                cur_cnt = 1

            if verse != cur_cnt:
                for j in range(verse - cur_cnt):
                    print(f"Missing verse: {chapter}:{cur_cnt}")
                    new_lines.append(f"{book} {chapter}:{cur_cnt} N/A")
                    cur_cnt += 1

            new_lines.append(line)
            prev_chapter = chapter
            cur_cnt += 1
    new_lines.append("")

    # Write the new content back to the file
    with open(f"{filename}", "w") as f:
        f.write("\n".join(new_lines))
