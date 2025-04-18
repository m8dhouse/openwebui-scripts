#!/usr/bin/env python3
import os
import json
import logging
import time
import traceback
import argparse
import unicodedata
import sys
import re
from logging.handlers import TimedRotatingFileHandler
from typing import Set, Dict, List, Optional, Any

# SQLAlchemy imports
from sqlalchemy import create_engine, text, Column, Integer, String, DateTime, JSON, ForeignKey, inspect
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Configuration variables
# Update the uploads directory path to match your environment
uploads_dir = "/usr/openweb/data/uploads/"
log_file = '/usr/openweb/orphanlog/cleanup_openui_orphans.log'

# Set up logging
os.makedirs(os.path.dirname(log_file), exist_ok=True)

# Configure logging with rotation
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger('cleanup_openui_orphans')
log.setLevel(logging.DEBUG)  # Set to DEBUG for detailed output during testing

# Add a rotating file handler
handler = TimedRotatingFileHandler(log_file, when='W0', interval=1, backupCount=4)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)

# Define SQLAlchemy models
Base = declarative_base()

class File(Base):
    __tablename__ = 'file'
    
    id = Column(String, primary_key=True)
    filename = Column(String)
    path = Column(String)
    
    def __repr__(self):
        return f"<File(id={self.id}, filename={self.filename})>"

class Document(Base):
    __tablename__ = 'document'
    
    id = Column(String, primary_key=True)
    filename = Column(String)
    path = Column(String)
    
    def __repr__(self):
        return f"<Document(id={self.id}, filename={self.filename})>"

class Chat(Base):
    __tablename__ = 'chat'
    
    id = Column(String, primary_key=True)
    title = Column(String)
    chat = Column(JSON)
    created_at = Column(Integer)
    updated_at = Column(Integer)
    
    def __repr__(self):
        return f"<Chat(id={self.id}, title={self.title})>"

def normalize_filename(filename: str) -> str:
    """
    Normalize a filename for case-insensitive comparison.
    
    Args:
        filename: The filename to normalize
        
    Returns:
        Normalized filename
    """
    # Normalize unicode characters
    filename = unicodedata.normalize('NFC', filename)
    # Strip leading and trailing whitespace
    filename = filename.strip()
    # Convert to lowercase for case-insensitive comparison
    filename = filename.lower()
    return filename

def inspect_database_schema(engine) -> bool:
    """
    Inspect the database schema to find the correct table names.
    
    Args:
        engine: SQLAlchemy engine
        
    Returns:
        True if schema inspection was successful, False otherwise
    """
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        log.info(f"Found tables in database: {tables}")
        
        # Check for file table
        file_table = None
        for table in tables:
            if table.lower() in ['file', 'files', 'attachment', 'attachments']:
                file_table = table
                break
        
        if file_table:
            log.info(f"Using '{file_table}' as the file table")
            File.__tablename__ = file_table
        else:
            log.error("Could not find a file table in the database")
            return False
        
        # Check for document table
        document_table = None
        for table in tables:
            if table.lower() in ['document', 'documents']:
                document_table = table
                break
        
        if document_table:
            log.info(f"Using '{document_table}' as the document table")
            Document.__tablename__ = document_table
        else:
            log.warning("Could not find a document table in the database")
            # Continue anyway, as we can still check for orphaned files
        
        # Check for chat table
        chat_table = None
        for table in tables:
            if table.lower() in ['chat', 'chats', 'conversation', 'conversations']:
                chat_table = table
                break
        
        if chat_table:
            log.info(f"Using '{chat_table}' as the chat table")
            Chat.__tablename__ = chat_table
        else:
            log.warning("Could not find a chat table in the database")
            # Continue anyway, as we can still check for orphaned files
        
        # Inspect columns in the file table
        if file_table:
            columns = inspector.get_columns(file_table)
            log.info(f"Columns in {file_table}: {[col['name'] for col in columns]}")
        
        # Inspect columns in the document table
        if document_table:
            columns = inspector.get_columns(document_table)
            log.info(f"Columns in {document_table}: {[col['name'] for col in columns]}")
        
        # Inspect columns in the chat table
        if chat_table:
            columns = inspector.get_columns(chat_table)
            log.info(f"Columns in {chat_table}: {[col['name'] for col in columns]}")
        
        return True
    except Exception as e:
        log.error(f"Error inspecting database schema: {e}")
        log.error(traceback.format_exc())
        return False

def get_db_session():
    """
    Create a database session.
    
    Returns:
        SQLAlchemy session
    """
    try:
        # Get database URL from environment or use default
        db_url = os.environ.get("DATABASE_URL", "postgresql://postgres:db@127.0.0.1:5432/openweb")
        log.info(f"Connecting to database: {db_url}")
        
        # Create engine
        engine = create_engine(db_url)
        
        # Inspect database schema
        if not inspect_database_schema(engine):
            log.error("Failed to inspect database schema")
            raise Exception("Database schema inspection failed")
        
        # Create session
        Session = sessionmaker(bind=engine)
        session = Session()
        
        return session
    except Exception as e:
        log.error(f"Error creating database session: {e}")
        log.error(traceback.format_exc())
        raise

def delete_file(file_path: str, dry_run: bool) -> bool:
    """
    Delete a file from the filesystem.
    
    Args:
        file_path: Path to the file to delete
        dry_run: If True, only log what would be deleted without actually deleting
        
    Returns:
        True if the file was deleted or would be deleted in dry run mode, False otherwise
    """
    if not dry_run:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                log.info("Deleted file %s", file_path)
                return True
            except Exception as e:
                log.error("Error deleting file %s: %s", file_path, e)
                log.error(traceback.format_exc())
                return False
        else:
            log.warning("File %s does not exist.", file_path)
            return False
    else:
        log.info("DRY RUN: Would delete file %s", file_path)
        return True

def extract_file_ids_from_chat(chat_data: Dict[str, Any]) -> Set[str]:
    """
    Extract file IDs from chat messages.
    
    Args:
        chat_data: Chat data dictionary
        
    Returns:
        Set of file IDs
    """
    file_ids = set()
    
    # Check if chat has messages
    if not chat_data or 'messages' not in chat_data:
        return file_ids
        
    # Extract file IDs from messages
    for message in chat_data['messages']:
        # Check for files in message
        if 'files' in message:
            for file in message['files']:
                if 'id' in file:
                    file_ids.add(file['id'])
                    
        # Check for file references in content
        if 'content' in message:
            content = message['content']
            # Look for file references in markdown
            if isinstance(content, str):
                # Simple markdown file reference pattern
                file_refs = re.findall(r'!\[.*?\]\(/api/v1/files/([^/]+)/content\)', content)
                file_ids.update(file_refs)
                
    return file_ids

def get_referenced_filenames(session) -> Set[str]:
    """
    Get all filenames referenced in the database.
    
    Args:
        session: SQLAlchemy session
        
    Returns:
        Set of normalized filenames
    """
    referenced_filenames = set()
    
    try:
        # Get filenames from file table
        try:
            result = session.execute(text(f"SELECT filename FROM {File.__tablename__}"))
            filenames_in_file_table = {
                normalize_filename(row[0]) for row in result if row[0]
            }
            referenced_filenames.update(filenames_in_file_table)
            log.info(f"Found {len(filenames_in_file_table)} filenames in {File.__tablename__} table")
        except Exception as e:
            log.error(f"Error getting filenames from {File.__tablename__} table: {e}")
            log.error(traceback.format_exc())
        
        # Get filenames from document table if it exists
        try:
            # Get all table names as strings
            table_names = inspect(session.get_bind()).get_table_names()
            if Document.__tablename__ in table_names:
                result = session.execute(text(f"SELECT filename FROM {Document.__tablename__}"))
                filenames_in_document_table = {
                    normalize_filename(row[0]) for row in result if row[0]
                }
                referenced_filenames.update(filenames_in_document_table)
                log.info(f"Found {len(filenames_in_document_table)} filenames in {Document.__tablename__} table")
        except Exception as e:
            log.error(f"Error getting filenames from {Document.__tablename__} table: {e}")
            log.error(traceback.format_exc())
        
        # Get filenames from knowledge table
        try:
            table_names = inspect(session.get_bind()).get_table_names()
            if KnowledgeModel.__tablename__ in table_names:
                # Get all knowledge bases
                result = session.execute(text(f"SELECT data FROM {KnowledgeModel.__tablename__}"))
                knowledge_file_ids = set()
                
                for row in result:
                    knowledge_data = row[0]
                    if knowledge_data and isinstance(knowledge_data, dict):
                        # Extract file IDs from knowledge base data
                        file_ids = knowledge_data.get("file_ids", [])
                        knowledge_file_ids.update(file_ids)
                
                # Get filenames for the file IDs
                if knowledge_file_ids:
                    try:
                        # Convert to list for SQL IN clause
                        file_id_list = list(knowledge_file_ids)
                        # Process in batches to avoid SQL IN clause limits
                        batch_size = 100
                        for i in range(0, len(file_id_list), batch_size):
                            batch = file_id_list[i:i+batch_size]
                            # Create a dictionary of parameters
                            params = {f'id_{j}': id for j, id in enumerate(batch)}
                            # Create placeholders with named parameters
                            placeholders = ','.join([f':id_{j}' for j in range(len(batch))])
                            result = session.execute(
                                text(f"SELECT filename FROM {File.__tablename__} WHERE id IN ({placeholders})"),
                                params
                            )
                            filenames_in_knowledge = {
                                normalize_filename(row[0]) for row in result if row[0]
                            }
                            referenced_filenames.update(filenames_in_knowledge)
                        
                        log.info(f"Found {len(knowledge_file_ids)} file IDs referenced in knowledge bases")
                    except Exception as e:
                        log.error(f"Error getting filenames for file IDs in knowledge bases: {e}")
                        log.error(traceback.format_exc())
        except Exception as e:
            log.error(f"Error getting filenames from knowledge table: {e}")
            log.error(traceback.format_exc())
        
        # Get filenames from chat messages if chat table exists
        try:
            table_names = inspect(session.get_bind()).get_table_names()
            if Chat.__tablename__ in table_names:
                # Get all chats
                result = session.execute(text(f"SELECT id, chat FROM {Chat.__tablename__}"))
                chat_file_ids = set()
                
                for row in result:
                    chat_id, chat_data = row
                    if chat_data:
                        try:
                            # Parse JSON if it's a string
                            if isinstance(chat_data, str):
                                try:
                                    chat_data = json.loads(chat_data)
                                except json.JSONDecodeError as e:
                                    log.error(f"Failed to parse JSON for chat ID {chat_id}: {e}")
                                    continue
                            
                            # Extract file IDs from chat
                            file_ids = extract_file_ids_from_chat(chat_data)
                            chat_file_ids.update(file_ids)
                        except Exception as e:
                            log.error(f"Error extracting file IDs from chat {chat_id}: {e}")
                            log.error(traceback.format_exc())
                
                # Get filenames for the file IDs
                if chat_file_ids:
                    try:
                        # Convert to list for SQL IN clause
                        file_id_list = list(chat_file_ids)
                        # Process in batches to avoid SQL IN clause limits
                        batch_size = 100
                        for i in range(0, len(file_id_list), batch_size):
                            batch = file_id_list[i:i+batch_size]
                            # Create a dictionary of parameters
                            params = {f'id_{j}': id for j, id in enumerate(batch)}
                            # Create placeholders with named parameters
                            placeholders = ','.join([f':id_{j}' for j in range(len(batch))])
                            result = session.execute(
                                text(f"SELECT filename FROM {File.__tablename__} WHERE id IN ({placeholders})"),
                                params
                            )
                            filenames_in_chats = {
                                normalize_filename(row[0]) for row in result if row[0]
                            }
                            referenced_filenames.update(filenames_in_chats)
                        
                        log.info(f"Found {len(chat_file_ids)} file IDs referenced in chats")
                    except Exception as e:
                        log.error(f"Error getting filenames for file IDs in chats: {e}")
                        log.error(traceback.format_exc())
        except Exception as e:
            log.error(f"Error getting filenames from chat messages: {e}")
            log.error(traceback.format_exc())
        
        log.info(f"Total filenames referenced in database: {len(referenced_filenames)}")
        return referenced_filenames
    except Exception as e:
        log.error(f"Error getting referenced filenames: {e}")
        log.error(traceback.format_exc())
        return set()

def get_files_in_uploads() -> Dict[str, str]:
    """
    Get all files in the uploads directory.
    
    Returns:
        Dictionary mapping normalized filenames to original filenames
    """
    try:
        if not os.path.exists(uploads_dir):
            log.error(f"Uploads directory {uploads_dir} does not exist")
            # Try to create the directory
            try:
                os.makedirs(uploads_dir, exist_ok=True)
                log.info(f"Created uploads directory: {uploads_dir}")
            except Exception as e:
                log.error(f"Failed to create uploads directory: {e}")
                log.error(traceback.format_exc())
            return {}
        
        original_files_in_uploads = os.listdir(uploads_dir)
        files_in_uploads = {normalize_filename(f): f for f in original_files_in_uploads}
        log.info(f"Total files in uploads directory: {len(files_in_uploads)}")
        return files_in_uploads
    except Exception as e:
        log.error(f"Error listing files in uploads directory: {e}")
        log.error(traceback.format_exc())
        return {}

def main(dry_run: bool = True) -> None:
    """
    Main function to clean up orphaned files.
    
    Args:
        dry_run: If True, only log what would be deleted without actually deleting
    """
    log.info("Starting orphan cleanup in %s mode.", 'DRY RUN' if dry_run else 'LIVE')
    log.debug("dry_run value: %s", dry_run)
    
    # Get database session
    session = None
    try:
        session = get_db_session()
        
        # Get all filenames referenced in the database
        referenced_filenames = get_referenced_filenames(session)
        
        # Get all files in the uploads directory
        files_in_uploads = get_files_in_uploads()
        
        # Identify orphaned files in uploads directory
        orphan_files_in_uploads = set(files_in_uploads.keys()) - referenced_filenames
        log.info(f"Orphaned files in uploads directory: {len(orphan_files_in_uploads)}")
        
        if orphan_files_in_uploads:
            log.info("Processing orphaned files in uploads directory...")
            
            # Limit the number of files to show in dry run mode to avoid memory issues
            files_to_process = list(orphan_files_in_uploads)
            if dry_run and len(files_to_process) > 10:
                log.info(f"DRY RUN: Showing first 10 of {len(files_to_process)} orphaned files")
                files_to_process = files_to_process[:10]
            
            deleted_count = 0
            for normalized_filename in files_to_process:
                try:
                    original_filename = files_in_uploads[normalized_filename]
                    file_path = os.path.join(uploads_dir, original_filename)
                    
                    # Log the reasoning for deletion
                    log.info(f"File '{original_filename}' is not referenced in the database and will be considered for deletion.")
                    
                    # Delete the physical file
                    if delete_file(file_path, dry_run):
                        deleted_count += 1
                except Exception as e:
                    log.error(f"Unexpected error processing file {normalized_filename}: {e}")
                    log.error(traceback.format_exc())
            
            if dry_run and len(orphan_files_in_uploads) > 10:
                log.info(f"DRY RUN: Would process {len(orphan_files_in_uploads)} orphaned files, would delete {deleted_count} files")
            else:
                log.info(f"Processed {len(files_to_process)} orphaned files, {'would have deleted' if dry_run else 'deleted'} {deleted_count} files.")
        else:
            log.info("No orphaned files found in the uploads directory.")
    
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")
        log.error(traceback.format_exc())
    finally:
        if session:
            session.close()
        log.info("Orphan cleanup complete.")

if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Cleanup orphaned files.')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without actually deleting')
    parser.add_argument('--db-url', type=str, help='Database URL (e.g., postgresql://user:pass@host:port/db)')
    parser.add_argument('--uploads-dir', type=str, help='Path to the uploads directory')
    args = parser.parse_args()
    
    # Debug information
    log.info("Python version: %s", sys.version)
    log.info("Current working directory: %s", os.getcwd())
    log.info("Starting orphan cleanup at %s", time.strftime('%Y-%m-%dT%H:%M:%S'))
    log.info("Dry run mode: %s", args.dry_run)
    
    # Set database URL from command line or environment
    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url
        log.info("Using database URL from command line: %s", args.db_url)
    elif "DATABASE_URL" not in os.environ:
        # Set default PostgreSQL connection details
        os.environ["DATABASE_URL"] = "postgresql://postgres:db@127.0.0.1:5432/openweb"
        log.info("Using default PostgreSQL connection: postgresql://postgres:db@127.0.0.1:5432/openweb")
    else:
        log.info("Using DATABASE_URL from environment: %s", os.environ["DATABASE_URL"])
    
    # Set uploads directory from command line if provided
    if args.uploads_dir:
        uploads_dir = args.uploads_dir
        log.info("Using uploads directory from command line: %s", uploads_dir)
    else:
        log.info("Using default uploads directory: %s", uploads_dir)
    
    # Check if psycopg2 is installed
    try:
        import psycopg2
        log.info("psycopg2 version: %s", psycopg2.__version__)
    except ImportError:
        log.error("psycopg2 is not installed. Please install it with: pip install psycopg2-binary")
        sys.exit(1)
    
    # Run the main function
    main(dry_run=args.dry_run) 
