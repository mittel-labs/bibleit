import os

import requests
import json

base_dir = "bolls/bibles"
# Load the JSON file
with open("bolls/books.json") as f:
    data = json.load(f)

# Base URL of the API endpoint
base_url = "https://bolls.life/get-text/"
# Translation to download
translation = "LUT"
# Output file
output_dir = f"{base_dir}/{translation}"

# Create the output directory if it doesn't exist
if not os.path.exists(output_dir):
    os.makedirs(output_dir, exist_ok=True)

# Iterate over each book in the JSON data
for book in data[translation]:
    book_id = book["bookid"]
    name = book["name"]
    chapters = book["chapters"]

    print(f"Downloading {name}...")

    # Create a string to hold all the chapters for the current book
    book_chapters_text = ""

    # Iterate over each chapter in the book
    for chapter in range(1, chapters + 1):
        print(f"Downloading chapter {chapter}...")
        # Construct the API URL for the chapter
        url = f"{base_url}{translation}/{book_id}/{chapter}/"

        # Send the HTTP GET request to the API
        response = requests.get(url)

        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            # Parse the JSON response
            chapter_data = response.json()

            # Create a string representation of the chapter
            chapter_text = ""
            line_prefix = f"{name} {chapter}:"

            for verse_data in chapter_data:
                verse_number = verse_data["verse"]
                verse_text = verse_data["text"]
                chapter_text += f"{line_prefix}{verse_number} {verse_text}\n"

            # Append the chapter content to the book_chapters_text
            book_chapters_text += f"{chapter_text}\n\n"

    # Save all chapters of the current book into a single file
    name_normalized = name.replace(" ", "_").replace("/", "_")
    file_name = f"{output_dir}/{book_id}_{name_normalized}.txt"
    with open(file_name, "w") as file:
        file.write(book_chapters_text)

    print(f"{name} downloaded successfully!")

print("All books downloaded successfully!")
