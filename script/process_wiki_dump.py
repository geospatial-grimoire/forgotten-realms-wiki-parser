# A script to parse a MediaWiki XML dump, clean the wikitext content,
# and save it as a structured Markdown file using the wikitextparser library.

import xml.etree.ElementTree as ET
import wikitextparser as wtp
from wikitextparser._wikitext import DeadIndexError
import configparser
import logging
import time
import re
import os
import sys
from datetime import datetime
from typing import Set, Optional
from urllib.parse import quote
from tqdm import tqdm

# ==============================================================================
# SETUP FUNCTIONS
# ==============================================================================

def setup_logging(log_dir: str, log_level: str) -> None:
    """Initializes logging to both a file and the console."""
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(log_dir, f"parser_{timestamp}.log")

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='w', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.info(f"Logging initialized. Log file at: {log_file}")

def get_excluded_namespaces(config: configparser.ConfigParser) -> Set[str]:
    """Reads the list of namespace prefixes to exclude from the config file."""
    namespaces_str = config.get('parser', 'excluded_namespaces', fallback='')
    return {ns.strip() for ns in namespaces_str.split(',') if ns.strip()}

def get_xml_namespace(filepath: str) -> Optional[str]:
    """
    Dynamically detects the XML namespace from the dump file's root element.
    This makes the script resilient to different MediaWiki export versions.
    """
    try:
        for event, elem in ET.iterparse(filepath, events=('start-ns',)):
            if elem[0] == '': return f"{{{elem[1]}}}"
    except (ET.ParseError, FileNotFoundError):
        return None
    return None

def count_total_pages(filepath: str, page_tag: str) -> int:
    """
    Performs a fast, memory-efficient first pass of the XML to count the total
    number of <page> elements, used for the progress bar.
    """
    count = 0
    try:
        for _, elem in ET.iterparse(filepath, events=('end',)):
            if elem.tag == page_tag:
                count += 1
            elem.clear() # Essential for memory efficiency
    except (ET.ParseError, FileNotFoundError):
        return 0
    return count

# ==============================================================================
# CORE PARSING LOGIC
# ==============================================================================

def clean_wikitext(wikitext: str, page_title: str) -> str:
    """
    Parses wikitext using a robust, structure-aware process with a final formatting pass.
    """
    if not wikitext or wikitext.lower().strip().startswith('#redirect'):
        return ""

    # Pass 1: Pre-processing with Regex.
    # This step handles specific data-carrying templates (like for units of measurement)
    # BEFORE the main parser sees them. This is a robust way to prevent data loss.
    try:
        wikitext = re.sub(r'\{\{\s*(?:sirange|SIrange)\s*\|([^}|]+)\|([^}|]+)\|([^}|]+)[^}]*\}\}', r'\1–\2 \3', wikitext, flags=re.IGNORECASE)
        wikitext = re.sub(r'\{\{\s*(?:sirange|SIrange)\s*\|([^}|]+)\|([^}|]+)[^}]*\}\}', r'\1–\2', wikitext, flags=re.IGNORECASE)
        wikitext = re.sub(r'\{\{\s*(?:si|SI)\s*\|([^}|]+)\|([^}|]+)[^}]*\}\}', r'\1 \2', wikitext, flags=re.IGNORECASE)
        wikitext = re.sub(r'\{\{\s*(?:si|SI)\s*\|([^}|]+)[^}]*\}\}', r'\1', wikitext, flags=re.IGNORECASE)

        parsed = wtp.parse(wikitext)
    except Exception as e:
        logging.error(f"Wikitextparser failed to parse article '{page_title}': {e}")
        return ""

    sections_to_remove = ["references", "see also", "notes", "appendix", "gallery", "external links", "connections", "further reading", "index"]
    templates_to_remove = {'navbox', 'stub', 'cleanup', 'citation needed', 'clarify', 'fact', 'update', 'wip', 'refs', 'see also', 'main', 'details'}

    # Pass 2: Remove large, unwanted sections by title.
    for section in parsed.sections[:]:
        try:
            if section.title and section.title.strip().lower() in sections_to_remove:
                del section[:]
        except (DeadIndexError, ValueError): continue
        except Exception as e: logging.warning(f"Could not remove a section in '{page_title}': {e}")

    # Pass 3: Handle cosmetic and structural templates.
    for template in parsed.templates[:]:
        try:
            template_name = template.name.strip().lower()

            if any(infobox_name in template_name for infobox_name in {'infobox', 'sidebar', 'creature'}):
                infobox_content = [f"- **{arg.name.strip()}:** {wtp.parse(arg.value.strip()).plain_text().strip()}" for arg in template.arguments if arg.name and arg.value and wtp.parse(arg.value.strip()).plain_text().strip()]
                template.string = "\n".join(infobox_content) if infobox_content else ""
            elif template_name in templates_to_remove:
                del template[:]
            elif template_name == 'frac' and len(template.arguments) >= 2:
                template.string = f"{template.arguments[0].value.strip()}/{template.arguments[1].value.strip()}"
            elif template_name == 'pronounce' and template.arguments:
                template.string = template.arguments[0].value.strip()
            elif template_name == 'singpl':
                template.string = ""
            elif template_name in ('quote', 'cquote') and template.arguments:
                quote_text = next((arg.value.strip() for arg in template.arguments if not arg.name.strip()), "")
                template.string = f"> {wtp.parse(quote_text).plain_text()}" if quote_text else ""
            else: # Remove any other unhandled templates to keep the output clean.
                del template[:]
        except (DeadIndexError, ValueError): continue
        except Exception:
            try: del template[:]
            except (ValueError, IndexError, DeadIndexError): pass

    # Pass 4: Find and convert all tables to Markdown.
    for table in parsed.tables[:]:
        try:
            table_data = table.data()
            if not table_data or not table_data[0]:
                del table[:]
                continue

            markdown_table = []
            header = [wtp.parse(str(cell)).plain_text().replace('\n', ' ').strip() for cell in table_data[0]]

            if not any(h for h in header):
                del table[:]
                continue

            markdown_table.append("| " + " | ".join(header) + " |")
            markdown_table.append("| " + " | ".join(['---'] * len(header)) + " |")

            for row in table_data[1:]:
                cleaned_row = [wtp.parse(str(cell)).plain_text().replace('\n', ' ').strip() for cell in row]
                if len(cleaned_row) == len(header):
                    markdown_table.append("| " + " | ".join(cleaned_row) + " |")

            if len(markdown_table) > 2:
                table.string = "\n".join(markdown_table)
            else:
                del table[:]
        except Exception as e:
            logging.warning(f"Could not process a table in page '{page_title}', skipping. Error: {e}")
            try:
                del table[:]
            except (ValueError, IndexError, DeadIndexError):
                pass

    # Pass 5: Convert the parsed object into a list of "raw" Markdown lines.
    raw_text = parsed.plain_text()
    lines = raw_text.split('\n')
    transformed_lines = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped_line = line.strip()
        lower_stripped_line = stripped_line.lower()

        # Filter out unwanted lines (metadata, etc.)
        if not stripped_line or \
           all(c in '• ' for c in stripped_line) or \
           stripped_line.startswith('Category:') or \
           lower_stripped_line.startswith('main article:') or \
           lower_stripped_line.startswith('for a list of') or \
           ':category:' in lower_stripped_line:
            transformed_lines.append('')
            i += 1
            continue

        # Context-aware merge for list items with descriptions on the next line
        if transformed_lines and transformed_lines[-1].endswith(':') and \
           not stripped_line.startswith(('*', '#', ';', ':', '=')):
            transformed_lines[-1] = transformed_lines[-1] + ' ' + stripped_line
            i += 1
            continue

        # Handle headings
        heading_match = re.match(r'^\s*(={2,6})\s*(.*?)\s*(=*)\s*$', stripped_line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip().rstrip(':')
            transformed_lines.append(f"{'#' * level} {title}")
            i += 1
            continue

        # Handle lists and pseudo-headers
        list_match = re.match(r'^([*#;:]+)\s*(.*)', stripped_line)
        if list_match:
            markers, item_text = list_match.groups()
            item_text = item_text.strip()

            # Context-aware check for single-item lists acting as subheadings
            if markers == '*':
                is_subheading = True
                next_line_index = i + 1
                while next_line_index < len(lines):
                    next_line = lines[next_line_index].strip()
                    if next_line:
                        if next_line.startswith('*'):
                            is_subheading = False
                        break
                    next_line_index += 1
                if is_subheading:
                    transformed_lines.append(f"**{item_text.rstrip(':')}:**")
                    i += 1
                    continue

            # Default list/pseudo-header processing
            if markers.startswith(';'):
                full_term_line = (markers[1:] + item_text).strip()
                parts = re.split(r':\s', full_term_line, 1)
                term = parts[0].strip().rstrip(':')
                definition = parts[1].strip() if len(parts) > 1 else ""
                transformed_lines.append(f"**{term}:**" + (f" {definition}" if definition else ""))
            elif markers.startswith(':'):
                 if '•' in item_text:
                    item_text = re.sub(r'\((.*?)\)', lambda m: f"({m.group(1).replace('•', ', ')})", item_text)
                    items = [item.strip() for item in item_text.split('•') if item.strip()]
                    transformed_lines.extend([f"- {item}" for item in items])
                 else:
                    transformed_lines.append(item_text)
            else: # Standard '*' and '#' lists
                indent = "  " * (len(markers) - 1)
                marker = '-' if markers.endswith('*') else '1.'
                if item_text.endswith(':'):
                    item_text = item_text.rstrip(':').strip()
                transformed_lines.append(f"{indent}{marker} {item_text}")
        else:
            transformed_lines.append(stripped_line)

        i += 1

    # Pass 6: Assemble the final text with consistent block spacing.
    final_output = []
    blocks = []
    current_block = []
    for line in transformed_lines:
        if line.strip():
            current_block.append(line)
        else:
            if current_block:
                blocks.append('\n'.join(current_block))
            current_block = []
    if current_block:
        blocks.append('\n'.join(current_block))

    final_text = '\n\n'.join(blocks)

    # Pass 7: Final aesthetic cleanup.
    final_text = re.sub(r'\s+([,.!?)])', r'\1', final_text) # Fix spacing before punctuation
    final_text = re.sub(r'\(\s*[;,]\s*\)', '', final_text) # Remove artifacts like (;)

    # Renumber ordered lists for clean raw Markdown.
    def renumber_list(match):
        list_block = match.group(0)
        lines = list_block.strip().split('\n')
        indent_match = re.match(r'^(\s*)', lines[0])
        indent = indent_match.group(1) if indent_match else ""

        renumbered_lines = []
        for i, line in enumerate(lines):
            # Perform the substitution outside of the f-string
            text_content = re.sub(r'^\s*1\.\s*', '', line)
            renumbered_lines.append(f"{indent}{i + 1}. {text_content}")

        return '\n'.join(renumbered_lines)

    list_pattern = re.compile(r'((?:^[ \t]*1\..*(?:\n|$))+)', re.MULTILINE)
    final_text = list_pattern.sub(renumber_list, final_text)

    return final_text

# ==============================================================================
# MAIN ORCHESTRATION
# ==============================================================================

def process_dump(config: configparser.ConfigParser, script_dir: str) -> None:
    """
    Main function to read the XML dump, iterate through pages, and write the output.
    """
    # File and path configuration
    input_filename = config.get('input', 'xml_dump_filename')
    input_path = os.path.join(script_dir, 'input', input_filename)
    output_dir = os.path.join(script_dir, 'output')
    os.makedirs(output_dir, exist_ok=True)

    # Use a generic output filename defined in the config
    output_filename = config.get('output', 'md_parsed_filename', fallback='wiki_output.md')
    output_path = os.path.join(output_dir, output_filename)

    # Parser and output settings
    excluded_namespaces = get_excluded_namespaces(config)
    base_url = config.get('wiki', 'base_url', fallback=None)
    start_index = config.getint('parser', 'start_index', fallback=0)
    end_index = config.getint('parser', 'end_index', fallback=0)
    license_text = config.get('output', 'license_text', fallback=None)

    logging.info(f"Input file: {input_path}")
    logging.info(f"Output file: {output_path}")

    # Dynamically find the XML namespace to avoid parsing errors.
    logging.info("Detecting XML namespace from the dump file...")
    xml_namespace = get_xml_namespace(input_path)
    if not xml_namespace:
        logging.critical(f"Could not determine XML namespace from '{input_path}'.")
        return
    logging.info(f"Successfully detected XML namespace: {xml_namespace}")

    if start_index > 0:
        logging.info(f"Processing slice from page {start_index}" + (f" to {end_index}." if end_index > 0 else " to the end."))

    # Define XML tags based on the detected namespace
    page_tag = f'{xml_namespace}page'
    title_path = f'./{xml_namespace}title'
    revision_path = f'./{xml_namespace}revision'
    text_path = f'./{xml_namespace}text'

    logging.info("Performing a quick scan to count total pages...")
    total_pages = count_total_pages(input_path, page_tag)
    if total_pages == 0:
        logging.critical(f"No <page> elements found using namespace '{xml_namespace}'.")
        return
    logging.info(f"Found {total_pages} total pages. Starting main processing...")

    page_count = 0
    processed_count = 0
    try:
        with open(output_path, 'w', encoding='utf-8') as outfile:
            # Add license header to the output file if provided in the config
            if license_text:
                outfile.write(f"{license_text.strip()}\n\n---\n\n")

            # Use iterparse for memory-efficient streaming of the large XML file.
            context = ET.iterparse(input_path, events=('end',))

            pbar_total = total_pages
            if start_index > 0:
                if end_index > 0 and end_index >= start_index:
                    pbar_total = end_index - start_index + 1
                else:
                    pbar_total = total_pages - start_index + 1 if total_pages > start_index else 0

            with tqdm(total=pbar_total, desc="Processing pages", unit=" pages", ascii=True, file=sys.stderr) as pbar:
                for _, elem in context:
                    if elem.tag == page_tag:
                        page_count += 1
                        # Handle slicing logic to process only a subset of pages
                        if start_index > 0 and page_count < start_index:
                            elem.clear()
                            continue
                        if end_index > 0 and page_count > end_index:
                            logging.info(f"Reached end index {end_index}. Stopping.")
                            elem.clear()
                            break

                        if (start_index == 0) or (page_count >= start_index):
                           pbar.update(1)

                        title_elem = elem.find(title_path)
                        revision_elem = elem.find(revision_path)
                        title = title_elem.text if title_elem is not None else ''
                        wikitext = ''
                        if revision_elem is not None:
                            text_elem = revision_elem.find(text_path)
                            if text_elem is not None and text_elem.text:
                                wikitext = text_elem.text

                        if title and wikitext:
                            # Filter pages based on namespace
                            if 'talk:' in title.lower() or any(title.startswith(ns) for ns in excluded_namespaces):
                                logging.debug(f"Skipping page in excluded namespace: {title}")
                            else:
                                try:
                                    # Call the main cleaning function
                                    cleaned_text = clean_wikitext(wikitext, title)
                                    if cleaned_text:
                                        outfile.write(f"# {title}\n\n")
                                        if base_url:
                                            url_title = quote(title.replace(' ', '_'))
                                            full_url = base_url + url_title
                                            outfile.write(f"> Article source: {full_url}\n\n")
                                        outfile.write(cleaned_text)
                                        outfile.write("\n\n---\n\n")
                                        processed_count += 1
                                except Exception as e:
                                    logging.error(f"Failed to process page '{title}': {e}", exc_info=True)

                        # Clear the element from memory to prevent high memory usage
                        elem.clear()

    except (FileNotFoundError, ET.ParseError) as e:
        logging.critical(f"A critical error occurred during file processing: {e}", exc_info=True)
        return
    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}", exc_info=True)
        return

    logging.info("Processing complete.")
    logging.info(f"Total articles processed and saved: {processed_count}.")

if __name__ == "__main__":
    start_time = time.time()
    try:
        script_dir = os.path.join(os.getcwd(), 'script')
        config_path = os.path.join(script_dir, 'config.ini')
        output_dir = os.path.join(script_dir, 'output')

        config = configparser.ConfigParser()
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found at {config_path}")
        config.read(config_path)

        setup_logging(output_dir, config.get('logging', 'log_level', fallback='INFO'))
        process_dump(config, script_dir)

    except Exception as e:
        # Fallback logging in case setup fails
        log_message = f"A critical error occurred in main execution: {e}"
        if 'logging' in globals() and logging.getLogger().hasHandlers():
            logging.critical(log_message, exc_info=True)
        else:
            print(log_message)

    end_time = time.time()
    elapsed_seconds = end_time - start_time
    minutes, seconds = divmod(elapsed_seconds, 60)

    # Final log message
    log_message = f"Total execution time: {int(minutes)} minutes and {seconds:.2f} seconds."
    if 'logging' in globals() and logging.getLogger().hasHandlers():
        logging.info(log_message)
    else:
        print(log_message)