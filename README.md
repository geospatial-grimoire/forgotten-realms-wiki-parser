# Forgotten Realms Wiki Parse

A script to parse the Forgotten Realms Wiki XML dump into a single, clean Markdown file.

## Overview

This script is designed to parse the large XML dump from the [Forgotten Realms Wiki](https://forgottenrealms.fandom.com), perform an advanced, multi-pass cleaning of the wikitext markup, and convert it into a single, well-structured Markdown file. The primary goal is to create a clean, readable corpus for fine-tuning Generative AI models or for use as a knowledge base.

While it could be adapted for other wikis, its cleaning and formatting rules have been specifically refined to handle the common patterns and templates found on the Forgotten Realms Wiki.

## How It Works

The script's core logic (`clean_wikitext` function) uses a multi-pass strategy to ensure maximum data preservation and correct formatting:

1.  **Pass 1: Regex Pre-processing:** Before the main parser even sees the text, a series of regular expressions find and replace specific data-carrying templates (like `{{SI}}` for units of measurement). This prevents critical data from being lost early in the process.
2.  **Pass 2: Structural Removal:** The script parses the wikitext and removes large, irrelevant sections (like "References", "See also", "Gallery") and noisy templates (like `{{Stub}}`, `{{Cleanup}}`).
3.  **Pass 3: Table Conversion:** It finds all standard wikitext tables and converts them into proper Markdown table format before they can be destroyed by the text-cleaning process.
4.  **Pass 4: Transformation to Markdown Lines:** The remaining semi-clean text is transformed line-by-line into basic Markdown elements. This is a context-aware pass that correctly handles various list types, headings, and pseudo-headings based on the surrounding lines.
5.  **Pass 5 & 6: Post-processing and Cleanup:** The generated Markdown is assembled into blocks with consistent spacing. A final pass re-numbers ordered lists and fixes minor punctuation and formatting artifacts.

## What Is Excluded (Default Configuration)

The script is configured to produce a clean corpus focused on lore. With the default `config.ini`, it automatically skips pages that are not part of the main encyclopedia, including:

- Any page with `talk:` in its title (case-insensitive).
- Pages from specific MediaWiki namespaces: `User`, `File`, `MediaWiki`, `Template`, `Help`, `Category`, `Portal`, `Module`, and `Draft`.
- Wiki-specific meta pages from the `Forgotten Realms Wiki:` namespace.

## Known Issues

-   **Complex Tables:** The script can fail to parse extremely complex or malformed wikitext tables. When this happens, a warning is logged (`Could not process a table...`), and the problematic table is removed from that article's output to prevent the entire script from crashing.
-   **Minor Whitespace Inconsistencies:** In some edge cases, the rule to have exactly one blank line between different content blocks may not work perfectly, resulting in a minor visual inconsistency. This does not affect the content's integrity.

## Example Output

This tool was successfully used to process the entire **Forgotten Realms Wiki** XML dump (`~366 MB`). You can view the resulting clean Markdown file (`~85 MB`) included in this repository as a live example:

➡️ **[script/output/forgottenrealms_pages.zip](script/output/forgottenrealms_pages.zip)**

## Example Use Case

The primary goal of this script is to create a clean, local knowledge base for use with large language models (LLMs). The resulting Markdown file is perfectly suited for **Retrieval-Augmented Generation (RAG)**.

You can simply feed the generated `.md` file to modern chat-based AI services that support file uploads, such as:

- **ChatGPT**
- **Microsoft Copilot**
- **Google Gemini**

By providing the file as context, you enable the AI to answer specific and detailed questions about the Forgotten Realms lore using a reliable, offline source of information, reducing hallucinations and improving the accuracy of its answers.

## A Note on Licensing

It is crucial to understand the distinction between the license for this **source code** and the license for the **data you process**.

- **This Tool's Code:** The code in this repository is licensed under the **MIT License**. You are free to use, modify, and distribute it as you see fit. See the [LICENSE](LICENSE) file for details.
- **The Wiki's Content:** The content of the wiki dump you download is covered by its **own license**. The file you generate is a **derivative work** of that content. You must respect the original license terms when using or sharing the output. Always check the licensing page of the source wiki.

## Prerequisites

-   Python 3.7+

## Installation

1.  Clone the repository:
    ```shell
    git clone [https://github.com/geospatial-grimoire/forgotten-realms-wiki-parser.git](https://github.com/geospatial-grimoire/forgotten-realms-wiki-parser.git)
    cd forgotten-realms-wiki-parser
    ```

2.  (Recommended) Create and activate a virtual environment:
    ```shell
    python3 -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3.  Install the required dependencies:
    ```shell
    pip install -r script/requirements.txt
    ```

## Usage

1.  **Download XML Dump:** Download a `forgottenrealms_pages_current.xml.7z` dump from the [FR Wiki Statistics](https://forgottenrealms.fandom.com/wiki/Special:Statistics) page (scroll down to see the links).

2.  **Prepare Input:** Decompress the `.7z` file and place the resulting `.xml` file inside the `script/input/` directory.

3.  **Configure:** Edit `script/config.ini` and set `xml_dump_filename` under the `[input]` section to match the name of your file. You can also customize the output filename and license text under the `[output]` section.


4.  **Run the Script:** From the root directory of the project (`forgotten-realms-wiki-parser/`), run:
    ```shell
    python3 script/process_wiki_dump.py
    ```

5.  **Check the Results:** The cleaned Markdown file and a detailed log file will be automatically saved in the `script/output/` directory.