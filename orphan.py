import os
import sqlite3
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import argparse
import unicodedata

# Configuration variables
db_path = "/usr/openweb/venv/lib/python3.11/site-packages/open_webui/data/webui.db"
uploads_dir = "/usr/openweb/venv/lib/python3.11/site-packages/open_webui/data/uploads/"
log_file = '/usr/openweb/orphanlog/cleanup_openui_orphans.log'  # Update this path to the desired log file location

def normalize_filename(filename):
    # Normalize unicode characters
    filename = unicodedata.normalize('NFC', filename)
    # Strip leading and trailing whitespace
    filename = filename.strip()
    # Convert to lowercase for case-insensitive comparison
    filename = filename.lower()
    return filename

def delete_file(file_path, test_mode):
    if not test_mode:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info("Deleted file %s", file_path)
            except Exception as e:
                logger.error("Error deleting file %s: %s", file_path, e)
        else:
            logger.warning("File %s does not exist.", file_path)
    else:
        logger.info("Test mode: Would delete file %s", file_path)

def main(test_mode):
    logger.info("Starting orphan cleanup in %s mode.", 'TEST' if test_mode else 'LIVE')
    logger.debug("test_mode value: %s", test_mode)

    if not os.path.exists(db_path):
        logger.error("Expected db at path %s to exist", db_path)
        return

    # Connect to the database
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
    except sqlite3.Error as e:
        logger.error("Failed to connect to the database: %s", e)
        return

    try:
        # Begin a transaction
        conn.execute('BEGIN')

        # Check if required tables exist
        required_tables = ['chat', 'file', 'document']
        for table in required_tables:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not cursor.fetchone():
                logger.error("Table '%s' does not exist in the database", table)
                conn.close()
                return

        # Collect all file IDs referenced in chats
        cursor.execute("SELECT chat FROM chat")
        chats = cursor.fetchall()
        file_ids_in_chats = set()

        for (chat_json,) in chats:
            try:
                chat_data = json.loads(chat_json)
                messages = chat_data.get('messages', [])
                for message in messages:
                    files = message.get('files', [])
                    for file_entry in files:
                        file_info = file_entry.get('file', {})
                        file_id = file_info.get('id')
                        if file_id:
                            file_ids_in_chats.add(file_id)
            except json.JSONDecodeError as e:
                logger.error("Failed to parse chat JSON: %s", e)
                continue

        logger.info("Total file IDs referenced in chats: %d", len(file_ids_in_chats))

        # Collect all file IDs from the 'file' table
        cursor.execute("SELECT id, filename FROM file")
        files_in_table = cursor.fetchall()
        file_ids_in_table = set()
        file_id_to_filename = {}

        for file_id, filename in files_in_table:
            file_ids_in_table.add(file_id)
            file_id_to_filename[file_id] = filename

        logger.info("Total file IDs in 'file' table: %d", len(file_ids_in_table))

        # Identify orphaned files in 'file' table (not referenced in chats)
        orphan_file_ids = file_ids_in_table - file_ids_in_chats
        logger.info("Orphaned file IDs in 'file' table: %d", len(orphan_file_ids))

        # Delete orphaned file records and files
        if orphan_file_ids:
            logger.info("Processing orphaned files in 'file' table...")

            for file_id in orphan_file_ids:
                try:
                    filename = file_id_to_filename.get(file_id)
                    file_path = os.path.join(uploads_dir, filename) if filename else None

                    # Log the reasoning for deletion
                    logger.info("File ID %s (%s) is not referenced in any chats and will be considered for deletion.", file_id, filename)

                    if not test_mode:
                        # Delete the file record from 'file' table
                        try:
                            cursor.execute("DELETE FROM file WHERE id = ?", (file_id,))
                            logger.info("Deleted file record with ID %s from 'file' table.", file_id)
                        except sqlite3.Error as e:
                            logger.error("Failed to delete file record with ID %s: %s", file_id, e)
                    else:
                        logger.info("Test mode: Would delete file record with ID %s", file_id)

                    # Delete the physical file (using delete_file function)
                    if file_path:
                        delete_file(file_path, test_mode)
                    else:
                        logger.warning("No filename found for file ID %s.", file_id)

                except Exception as e:
                    logger.error("Unexpected error processing file ID %s: %s", file_id, e)
                    # Continue processing the next file

        # Now check for orphaned files in uploads directory
        logger.info("Checking for orphaned files in uploads directory...")

        # Get all filenames from 'file' and 'document' tables and normalize them
        cursor.execute("SELECT filename FROM file")
        filenames_in_file_table = {
            normalize_filename(row[0]) for row in cursor.fetchall() if row[0]
        }

        cursor.execute("SELECT filename FROM document")
        filenames_in_document_table = {
            normalize_filename(row[0]) for row in cursor.fetchall() if row[0]
        }

        referenced_filenames = filenames_in_file_table.union(filenames_in_document_table)
        logger.info("Total filenames referenced in 'file' and 'document' tables: %d", len(referenced_filenames))
        logger.debug("Referenced filenames: %s", referenced_filenames)

        # List all files in the uploads directory and normalize them
        try:
            files_in_uploads = {normalize_filename(f) for f in os.listdir(uploads_dir)}
        except Exception as e:
            logger.error("Error listing files in uploads directory: %s", e)
            files_in_uploads = set()

        logger.info("Total files in uploads directory: %d", len(files_in_uploads))
        logger.debug("Files in uploads directory: %s", files_in_uploads)

        # Identify orphaned files in uploads directory
        orphan_files_in_uploads = files_in_uploads - referenced_filenames
        logger.info("Orphaned files in uploads directory: %d", len(orphan_files_in_uploads))
        logger.debug("Orphaned files: %s", orphan_files_in_uploads)

        if orphan_files_in_uploads:
            logger.info("Processing orphaned files in uploads directory...")

            for filename in orphan_files_in_uploads:
                try:
                    # Find the original filename (without normalization) to construct the file path
                    matching_files = [f for f in os.listdir(uploads_dir) if normalize_filename(f) == filename]
                    if matching_files:
                        original_filename = matching_files[0]
                        file_path = os.path.join(uploads_dir, original_filename)
                    else:
                        file_path = os.path.join(uploads_dir, filename)  # Fallback in case of mismatch
                        original_filename = filename

                    # Log the reasoning for deletion
                    logger.info("File '%s' is not referenced in the 'file' or 'document' tables and will be considered for deletion.", original_filename)

                    # Delete the physical file (using delete_file function)
                    delete_file(file_path, test_mode)

                except Exception as e:
                    logger.error("Unexpected error processing file %s: %s", filename, e)
                    # Continue processing the next file

        # Commit or rollback the transaction
        if not test_mode:
            conn.commit()
            logger.info("LIVE mode: Changes committed to the database.")
        else:
            conn.rollback()
            logger.info("Test mode: Rolled back any changes.")

    except Exception as e:
        logger.error("An unexpected error occurred: %s", e)
        conn.rollback()
    finally:
        conn.close()
        logger.info("Orphan cleanup complete.")

if __name__ == "__main__":
    # Configure logging
    logger = logging.getLogger('cleanup_openui_orphans')
    logger.setLevel(logging.DEBUG)  # Set to DEBUG for detailed output during testing

    # Create a TimedRotatingFileHandler that rotates logs every week
    handler = TimedRotatingFileHandler(log_file, when='W0', interval=1, backupCount=4)
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Cleanup orphaned files and records.')
    parser.add_argument('--test', choices=['Y', 'N'], default='Y', help='Test mode (Y/N). Default is Y.')
    args = parser.parse_args()

    test_mode = True if args.test.strip().upper() == 'Y' else False
    logger.debug("Command-line argument --test: %s", args.test)
    logger.debug("Parsed test_mode: %s", test_mode)

    main(test_mode)
