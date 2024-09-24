import os
import sqlite3
import time
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import argparse

# Configuration variables
db_path = "/usr/openweb/venv/lib/python3.11/site-packages/open_webui/data/webui.db"
uploads_dir = "/usr/openweb/venv/lib/python3.11/site-packages/open_webui/data/uploads/"
cleanup_days = 30  # Number of days after which chats and files will be deleted
log_file = '/usr/openweb/cleanlog/cleanup_openui.log'  # Update this path to the desired log file location

def is_unix_timestamp(s):
    try:
        timestamp = int(s)
        return timestamp > 1_700_000_000
    except (ValueError, TypeError):
        raise ValueError(f"Could not parse timestamp: {s}")

def main():
    parser = argparse.ArgumentParser(description='Cleanup old chats and files.')
    parser.add_argument('--test', choices=['Y', 'N'], default='N', help='Test mode (Y/N)')
    args = parser.parse_args()

    TEST = args.test

    logger.info("Starting cleanup at %s", time.strftime('%Y-%m-%dT%H:%M:%S'))
    logger.info("Test mode is %s", TEST)

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

    if TEST == 'N':
        # Begin a transaction
        conn.execute('BEGIN')

    try:
        # Check if 'chat' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat'")
        if not cursor.fetchone():
            logger.error("Table 'chat' does not exist in the database")
            conn.close()
            return

        # Check if 'file' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='file'")
        if not cursor.fetchone():
            logger.error("Table 'file' does not exist in the database")
            conn.close()
            return

        # Get timestamp of cleanup_days ago
        cleanup_threshold = int(time.time()) - cleanup_days * 24 * 60 * 60

        # Select chat IDs and 'chat' JSON to delete
        try:
            cursor.execute("SELECT id, chat FROM chat WHERE updated_at < ? AND archived != 1", (cleanup_threshold,))
            chats_to_delete = cursor.fetchall()
        except sqlite3.Error as e:
            logger.error("Failed to execute SELECT query: %s", e)
            conn.close()
            return

        if not chats_to_delete:
            logger.info("No chats to delete.")
        else:
            chat_ids = [chat_row[0] for chat_row in chats_to_delete]
            logger.info("Found %d chats with IDs: %s", len(chat_ids), chat_ids)

            # For each chat, parse the 'chat' JSON to find associated file IDs
            file_ids_to_delete = set()

            for chat_id, chat_json in chats_to_delete:
                try:
                    chat_data = json.loads(chat_json)
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse JSON for chat ID %s: %s", chat_id, e)
                    continue

                messages = chat_data.get('messages', [])
                for message in messages:
                    files = message.get('files', [])
                    for file_entry in files:
                        file_info = file_entry.get('file', {})
                        file_id = file_info.get('id')
                        if file_id:
                            file_ids_to_delete.add(file_id)

            # Now, get filenames from 'file' table for these file_ids
            file_paths_to_delete = set()

            if file_ids_to_delete:
                placeholders = ','.join(['?'] * len(file_ids_to_delete))
                try:
                    cursor.execute(f"SELECT id, filename FROM file WHERE id IN ({placeholders})", list(file_ids_to_delete))
                    file_rows = cursor.fetchall()
                except sqlite3.Error as e:
                    logger.error("Failed to retrieve filenames from 'file' table: %s", e)
                    conn.close()
                    return

                for file_id, filename in file_rows:
                    file_path = os.path.join(uploads_dir, filename)
                    file_paths_to_delete.add(file_path)

            if TEST == 'N':
                logger.info("Deleting %d file records from 'file' table", len(file_ids_to_delete))
                # Delete file records from 'file' table
                placeholders = ','.join(['?'] * len(file_ids_to_delete))
                try:
                    cursor.execute(f"DELETE FROM file WHERE id IN ({placeholders})", list(file_ids_to_delete))
                except sqlite3.Error as e:
                    logger.error("Failed to delete file records: %s", e)
                    # Do not rollback yet; continue to try to delete chats
            else:
                logger.info("Would delete %d file records from 'file' table", len(file_ids_to_delete))
                for file_id in file_ids_to_delete:
                    logger.info("Would delete file record with ID %s from 'file' table", file_id)

            # Delete files from uploads directory
            if TEST == 'N':
                logger.info("Deleting %d files from uploads directory", len(file_paths_to_delete))
            else:
                logger.info("Would delete %d files from uploads directory", len(file_paths_to_delete))
            for file_path in file_paths_to_delete:
                if os.path.exists(file_path):
                    if TEST == 'N':
                        try:
                            os.remove(file_path)
                            logger.info("Deleted file %s", file_path)
                        except Exception as e:
                            logger.error("Error deleting file %s: %s", file_path, e)
                            continue  # Continue processing other files
                    else:
                        logger.info("Would delete file %s", file_path)
                else:
                    # File does not exist; no action needed
                    logger.warning("File %s does not exist", file_path)

            # Delete chats from database
            if TEST == 'N':
                try:
                    placeholders = ','.join(['?'] * len(chat_ids))
                    cursor.execute(f"DELETE FROM chat WHERE id IN ({placeholders})", chat_ids)
                    logger.info("Deleted %d chats from the database.", cursor.rowcount)
                except sqlite3.Error as e:
                    logger.error("Failed to delete chats: %s", e)
                    conn.rollback()
                    conn.close()
                    return
            else:
                logger.info("Would delete %d chats from the database with IDs: %s", len(chat_ids), chat_ids)

        # Commit the transaction
        if TEST == 'N':
            conn.commit()

    except Exception as e:
        logger.error("An unexpected error occurred: %s", e)
        if TEST == 'N':
            conn.rollback()
    finally:
        conn.close()
        logger.info("Cleanup complete.")

if __name__ == "__main__":
    # Configure logging
    logger = logging.getLogger('cleanup_openui')
    logger.setLevel(logging.INFO)

    # Create a TimedRotatingFileHandler that rotates logs every week
    # 'when' can be 'W0' - roll over at midnight on Monday
    # 'backupCount' specifies how many backup files to keep
    handler = TimedRotatingFileHandler(log_file, when='W0', interval=1, backupCount=4)
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    main()
