#!/usr/bin/env python3
import logging
import time
import os
import sys
import traceback
import argparse
import json
from typing import List, Set, Tuple, Dict, Any, Optional, Generator
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler

# SQLAlchemy imports
from sqlalchemy import create_engine, text, Column, Integer, String, DateTime, JSON, ForeignKey, inspect, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Set up logging
log_file = '/usr/openweb/cleanlog/cleanup_openui.log'
os.makedirs(os.path.dirname(log_file), exist_ok=True)

# Configure logging with rotation
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Add a rotating file handler
handler = TimedRotatingFileHandler(log_file, when='W0', interval=1, backupCount=4)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)

# Define SQLAlchemy models
Base = declarative_base()

# Configuration variables
uploads_dir = "/usr/openweb/data/uploads/"
chroma_dir = "/usr/openweb/data/chroma/"

# Create directories if they don't exist
os.makedirs(uploads_dir, exist_ok=True)
os.makedirs(chroma_dir, exist_ok=True)

class Chat(Base):
    __tablename__ = 'chat'  # Changed from 'chats' to 'chat'
    
    id = Column(String, primary_key=True)
    title = Column(String)
    chat = Column(JSON)
    created_at = Column(Integer)
    updated_at = Column(Integer)
    archived = Column(Boolean, default=False)  # Add archived flag
    
    def __repr__(self):
        return f"<Chat(id={self.id}, title={self.title})>"

class File(Base):
    __tablename__ = 'file'  # Changed from 'files' to 'file'
    
    id = Column(String, primary_key=True)
    filename = Column(String)
    path = Column(String)
    
    def __repr__(self):
        return f"<File(id={self.id}, filename={self.filename})>"

def inspect_database_schema(engine):
    """Inspect the database schema to find the correct table names."""
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        log.info(f"Found tables in database: {tables}")
        
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
            log.error("Could not find a chat table in the database")
            return False
        
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
        
        # Inspect columns in the chat table
        if chat_table:
            columns = inspector.get_columns(chat_table)
            log.info(f"Columns in {chat_table}: {[col['name'] for col in columns]}")
            
            # Check if archived column exists
            has_archived = any(col['name'] == 'archived' for col in columns)
            if not has_archived:
                log.warning("No 'archived' column found in chat table. Archived chats will not be excluded.")
        
        # Inspect columns in the file table
        if file_table:
            columns = inspector.get_columns(file_table)
            log.info(f"Columns in {file_table}: {[col['name'] for col in columns]}")
        
        return True
    except Exception as e:
        log.error(f"Error inspecting database schema: {e}")
        log.error(traceback.format_exc())
        return False

def get_db_session():
    """Create a database session."""
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

def extract_file_ids_from_chat(chat_data: Dict[str, Any]) -> Set[str]:
    """Extract file IDs from chat messages."""
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
                import re
                file_refs = re.findall(r'!\[.*?\]\(/api/v1/files/([^/]+)/content\)', content)
                file_ids.update(file_refs)
                
    return file_ids

def get_old_chat_ids(days_threshold: int, session) -> List[str]:
    """
    Get IDs of chats older than the specified number of days.
    This is more memory-efficient than loading the entire chat objects.
    
    Args:
        days_threshold: Number of days after which chats should be deleted
        session: Database session
        
    Returns:
        List of chat IDs
    """
    # Calculate timestamp threshold
    current_time = int(time.time())
    threshold_time = current_time - (days_threshold * 24 * 60 * 60)
    
    log.info(f"Getting IDs of chats older than {days_threshold} days (before {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(threshold_time))})")
    
    # Query for chat IDs only
    chat_ids = []
    batch_size = 1000
    offset = 0
    
    # Check if archived column exists
    has_archived = False
    try:
        result = session.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{Chat.__tablename__}' AND column_name = 'archived'"))
        has_archived = result.fetchone() is not None
    except Exception as e:
        log.warning(f"Error checking for archived column: {e}")
    
    while True:
        try:
            # Use a raw SQL query to get just the IDs
            if has_archived:
                # Exclude archived chats
                result = session.execute(
                    text(f"SELECT id FROM {Chat.__tablename__} WHERE updated_at < :threshold AND (archived IS NULL OR archived = FALSE) ORDER BY id LIMIT :limit OFFSET :offset"),
                    {"threshold": threshold_time, "limit": batch_size, "offset": offset}
                )
            else:
                # No archived column, get all old chats
                result = session.execute(
                    text(f"SELECT id FROM {Chat.__tablename__} WHERE updated_at < :threshold ORDER BY id LIMIT :limit OFFSET :offset"),
                    {"threshold": threshold_time, "limit": batch_size, "offset": offset}
                )
            
            batch = [row[0] for row in result]
            if not batch:
                break
                
            chat_ids.extend(batch)
            log.info(f"Found {len(chat_ids)} old chat IDs so far...")
            offset += batch_size
        except Exception as e:
            log.error(f"Error querying old chat IDs: {e}")
            log.error(traceback.format_exc())
            break
    
    log.info(f"Found {len(chat_ids)} chat IDs older than {days_threshold} days")
    return chat_ids

def get_chat_by_id(session, chat_id: str) -> Optional[Chat]:
    """Get a chat by ID."""
    try:
        return session.query(Chat).filter_by(id=chat_id).first()
    except Exception as e:
        log.error(f"Error getting chat {chat_id}: {e}")
        log.error(traceback.format_exc())
        return None

def get_file_ids_for_chats(session, chat_ids: List[str]) -> Set[str]:
    """
    Get file IDs associated with the given chat IDs.
    This is more memory-efficient than loading all chats.
    
    Args:
        session: Database session
        chat_ids: List of chat IDs
        
    Returns:
        Set of file IDs
    """
    all_file_ids = set()
    batch_size = 100
    total_chats = len(chat_ids)
    
    for i in range(0, total_chats, batch_size):
        batch = chat_ids[i:i+batch_size]
        log.info(f"Processing chat batch {i//batch_size + 1}/{(total_chats + batch_size - 1)//batch_size} for file IDs...")
        
        for chat_id in batch:
            try:
                chat = get_chat_by_id(session, chat_id)
                if chat and chat.chat:
                    try:
                        # Parse JSON if it's a string
                        chat_data = chat.chat
                        if isinstance(chat_data, str):
                            try:
                                chat_data = json.loads(chat_data)
                            except json.JSONDecodeError as e:
                                log.error(f"Failed to parse JSON for chat ID {chat_id}: {e}")
                                continue
                                
                        file_ids = extract_file_ids_from_chat(chat_data)
                        all_file_ids.update(file_ids)
                    except Exception as e:
                        log.error(f"Error extracting file IDs from chat {chat_id}: {e}")
                        log.error(traceback.format_exc())
            except Exception as e:
                log.error(f"Error processing chat {chat_id}: {e}")
                log.error(traceback.format_exc())
    
    log.info(f"Found {len(all_file_ids)} files associated with {total_chats} old chats")
    return all_file_ids

def find_old_chats_and_files(days_threshold: int = 45) -> Tuple[List[str], Set[str]]:
    """
    Find chat IDs and their associated file IDs that are older than the specified number of days.
    
    Args:
        days_threshold: Number of days after which chats should be deleted
        
    Returns:
        Tuple containing list of old chat IDs and set of file IDs
    """
    # Get database session
    session = None
    try:
        session = get_db_session()
        
        # Debug: Count total chats
        try:
            total_chats = session.query(Chat).count()
            log.info(f"Total chats in database: {total_chats}")
        except Exception as e:
            log.error(f"Error counting chats: {e}")
            log.error(traceback.format_exc())
            return [], set()
        
        # Debug: Get the oldest and newest chat timestamps
        try:
            oldest_chat = session.query(Chat).order_by(Chat.updated_at.asc()).first()
            newest_chat = session.query(Chat).order_by(Chat.updated_at.desc()).first()
            
            if oldest_chat:
                log.info(f"Oldest chat timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(oldest_chat.updated_at))}")
            if newest_chat:
                log.info(f"Newest chat timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(newest_chat.updated_at))}")
        except Exception as e:
            log.error(f"Error getting chat timestamps: {e}")
            log.error(traceback.format_exc())
        
        # Get old chat IDs
        old_chat_ids = get_old_chat_ids(days_threshold, session)
        
        if not old_chat_ids:
            log.info("No old chats found to clean up")
            return [], set()
        
        # Get file IDs for old chats
        all_file_ids = get_file_ids_for_chats(session, old_chat_ids)
        
        return old_chat_ids, all_file_ids
    except Exception as e:
        log.error(f"Error finding old chats and files: {e}")
        log.error(traceback.format_exc())
        return [], set()
    finally:
        if session:
            session.close()

def delete_file(file_id: str, session, dry_run: bool = True) -> bool:
    """
    Delete a file from the database and filesystem.
    
    Args:
        file_id: ID of the file to delete
        session: Database session
        dry_run: If True, only log what would be deleted without actually deleting
        
    Returns:
        True if the file was deleted or would be deleted in dry run mode, False otherwise
    """
    try:
        # Get the file from the database
        file = session.query(File).filter(File.id == file_id).first()
        if not file:
            log.warning(f"File {file_id} not found in database, skipping deletion")
            return True  # Return True to continue processing
            
        # Get the file path
        file_path = os.path.join(uploads_dir, file.filename)
        
        # Delete the physical file
        if not dry_run:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    log.info(f"Deleted file {file_path}")
                except Exception as e:
                    log.error(f"Error deleting file {file_path}: {e}")
                    log.error(traceback.format_exc())
                    return False
            else:
                log.warning(f"File {file_path} does not exist, skipping deletion")
        
        # Delete the database record
        if not dry_run:
            try:
                session.delete(file)
                session.commit()
                log.info(f"Deleted file record {file_id} from database")
            except Exception as e:
                log.error(f"Error deleting file record {file_id} from database: {e}")
                log.error(traceback.format_exc())
                session.rollback()
                return False
        else:
            log.info(f"DRY RUN: Would delete file {file_path} and database record {file_id}")
        
        return True
    except Exception as e:
        log.error(f"Error deleting file {file_id}: {e}")
        log.error(traceback.format_exc())
        return False

def delete_chat(session, chat_id: str) -> bool:
    """Delete a chat by ID."""
    try:
        chat = session.query(Chat).filter_by(id=chat_id).first()
        if chat:
            session.delete(chat)
            session.commit()
            log.info(f"Deleted chat {chat_id} from database")
            return True
        log.warning(f"Chat {chat_id} not found in database, skipping deletion")
        return False
    except Exception as e:
        log.error(f"Error deleting chat {chat_id}: {e}")
        log.error(traceback.format_exc())
        session.rollback()
        return False

def compact_postgresql(dry_run: bool = False) -> None:
    """
    Compact PostgreSQL database by running VACUUM ANALYZE.
    
    Args:
        dry_run: If True, only show what would be done without actually doing it
    """
    try:
        # Get database URL from environment or use default
        db_url = os.environ.get("DATABASE_URL", "postgresql://postgres:db@127.0.0.1:5432/openweb")
        
        if dry_run:
            log.info("DRY RUN: Would run VACUUM ANALYZE on PostgreSQL database")
            return
            
        log.info("Running VACUUM ANALYZE on PostgreSQL database...")
        
        # Use direct psycopg2 connection instead of SQLAlchemy for VACUUM
        import psycopg2
        from urllib.parse import urlparse
        
        # Parse the database URL
        parsed = urlparse(db_url)
        dbname = parsed.path[1:]  # Remove leading slash
        user = parsed.username
        password = parsed.password
        host = parsed.hostname
        port = parsed.port or 5432
        
        # Connect directly with psycopg2
        conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port
        )
        
        # Set autocommit to True to avoid transaction block
        conn.autocommit = True
        
        try:
            with conn.cursor() as cursor:
                cursor.execute("VACUUM ANALYZE")
            log.info("PostgreSQL database compaction completed")
        except Exception as e:
            log.error(f"Error running VACUUM ANALYZE: {e}")
            log.error(traceback.format_exc())
            log.info("PostgreSQL compaction skipped due to permission issues")
        finally:
            conn.close()
        
    except Exception as e:
        log.error(f"Error compacting PostgreSQL database: {e}")
        log.error(traceback.format_exc())

def compact_chromadb(dry_run: bool = False) -> None:
    """
    Compact ChromaDB by running vacuum.
    
    Args:
        dry_run: If True, only show what would be done without actually doing it
    """
    try:
        if dry_run:
            log.info("DRY RUN: Would run VACUUM on ChromaDB")
            return
            
        log.info("Running VACUUM on ChromaDB...")
        
        # Check if ChromaDB is installed
        try:
            import chromadb
            from chromadb.config import Settings
            
            # Initialize ChromaDB client
            client = chromadb.PersistentClient(path=chroma_dir)
            
            # Get all collections
            collections = client.list_collections()
            
            if not collections:
                log.info("No ChromaDB collections found to vacuum")
                return
                
            log.info(f"Found {len(collections)} ChromaDB collections to vacuum")
            
            # Vacuum each collection
            for collection in collections:
                try:
                    collection_name = collection.name
                    log.info(f"Vacuuming ChromaDB collection: {collection_name}")
                    
                    # Get collection
                    coll = client.get_collection(collection_name)
                    
                    # Run vacuum
                    coll.persist()
                    
                    log.info(f"Successfully vacuumed ChromaDB collection: {collection_name}")
                except Exception as e:
                    log.error(f"Error vacuuming ChromaDB collection {collection_name}: {e}")
                    log.error(traceback.format_exc())
            
            log.info("ChromaDB vacuum completed")
        except ImportError:
            log.warning("ChromaDB not installed, skipping ChromaDB vacuum")
        except Exception as e:
            log.error(f"Error vacuuming ChromaDB: {e}")
            log.error(traceback.format_exc())
            
    except Exception as e:
        log.error(f"Error in ChromaDB vacuum process: {e}")
        log.error(traceback.format_exc())

def cleanup_old_chats(days_threshold: int = 45, dry_run: bool = False) -> None:
    """
    Delete chats and their associated files that are older than the specified number of days.
    Also compact PostgreSQL database and ChromaDB.
    
    Args:
        days_threshold: Number of days after which chats should be deleted
        dry_run: If True, only show what would be deleted without actually deleting
    """
    try:
        # Find old chats and files
        old_chat_ids, all_file_ids = find_old_chats_and_files(days_threshold)
        
        if not old_chat_ids and not dry_run:
            # Even if no chats to delete, we might still want to compact databases
            compact_postgresql(dry_run)
            compact_chromadb(dry_run)
            return
            
        if dry_run:
            log.info(f"DRY RUN: Would delete {len(old_chat_ids)} chats and {len(all_file_ids)} files")
            
            # Show chat details - limit to first 10 to avoid memory issues
            session = None
            try:
                session = get_db_session()
                for i, chat_id in enumerate(old_chat_ids[:10]):
                    chat = get_chat_by_id(session, chat_id)
                    if chat:
                        log.info(f"DRY RUN: Would delete chat {chat.id} - Title: {chat.title} - Updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(chat.updated_at))}")
                
                if len(old_chat_ids) > 10:
                    log.info(f"DRY RUN: ... and {len(old_chat_ids) - 10} more chats")
            finally:
                if session:
                    session.close()
            
            # Show file details - limit to first 10 to avoid memory issues
            session = None
            try:
                session = get_db_session()
                for i, file_id in enumerate(list(all_file_ids)[:10]):
                    file = session.query(File).filter_by(id=file_id).first()
                    if file:
                        log.info(f"DRY RUN: Would delete file {file_id} - Name: {file.filename} - Path: {file.path}")
                    else:
                        log.info(f"DRY RUN: Would skip file {file_id} - Not found in database")
                
                if len(all_file_ids) > 10:
                    log.info(f"DRY RUN: ... and {len(all_file_ids) - 10} more files")
            finally:
                if session:
                    session.close()
            
            # Show database compaction details
            compact_postgresql(dry_run)
            compact_chromadb(dry_run)
            
            return
        
        # Delete files and chats
        session = None
        try:
            session = get_db_session()
            
            # Delete files from storage and database
            deleted_files = 0
            skipped_files = 0
            batch_size = 100
            file_ids_list = list(all_file_ids)
            
            for i in range(0, len(file_ids_list), batch_size):
                batch = file_ids_list[i:i+batch_size]
                log.info(f"Deleting file batch {i//batch_size + 1}/{(len(file_ids_list) + batch_size - 1)//batch_size}...")
                
                for file_id in batch:
                    try:
                        # Delete file
                        if delete_file(file_id, session, dry_run):
                            deleted_files += 1
                    except Exception as e:
                        log.error(f"Error deleting file {file_id}: {e}")
                        log.error(traceback.format_exc())
                        skipped_files += 1
            
            # Delete old chats
            deleted_chats = 0
            skipped_chats = 0
            batch_size = 100
            
            for i in range(0, len(old_chat_ids), batch_size):
                batch = old_chat_ids[i:i+batch_size]
                log.info(f"Deleting chat batch {i//batch_size + 1}/{(len(old_chat_ids) + batch_size - 1)//batch_size}...")
                
                for chat_id in batch:
                    try:
                        chat = get_chat_by_id(session, chat_id)
                        if not chat:
                            log.warning(f"Chat {chat_id} not found in database, skipping deletion")
                            skipped_chats += 1
                            continue
                            
                        if delete_chat(session, chat_id):
                            deleted_chats += 1
                    except Exception as e:
                        log.error(f"Error deleting chat {chat_id}: {e}")
                        log.error(traceback.format_exc())
                        skipped_chats += 1
            
            log.info(f"Successfully cleaned up {deleted_chats} old chats and {deleted_files} associated files")
            if skipped_files > 0:
                log.info(f"Skipped {skipped_files} files that were not found in the database")
            if skipped_chats > 0:
                log.info(f"Skipped {skipped_chats} chats that were not found in the database")
        finally:
            if session:
                session.close()
        
        # Compact databases after deletion
        compact_postgresql(dry_run)
        compact_chromadb(dry_run)
            
    except Exception as e:
        log.error(f"Error during cleanup: {e}")
        log.error(traceback.format_exc())

def main():
    """Main function."""
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Clean up old chats and their associated files')
    parser.add_argument('--days', type=int, default=45, help='Number of days after which chats should be deleted (default: 45)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted without actually deleting')
    parser.add_argument('--db-url', type=str, help='Database URL (e.g., postgresql://user:pass@host:port/db)')
    parser.add_argument('--chroma-dir', type=str, help='Path to ChromaDB directory')
    args = parser.parse_args()
    
    # Debug information
    log.info("Python version: %s", sys.version)
    log.info("Current working directory: %s", os.getcwd())
    log.info("Starting cleanup at %s", time.strftime('%Y-%m-%dT%H:%M:%S'))
    log.info("Dry run mode: %s", args.dry_run)
    
    # Check if psycopg2 is installed
    try:
        import psycopg2
        log.info("psycopg2 version: %s", psycopg2.__version__)
    except ImportError:
        log.error("psycopg2 is not installed. Please install it with: pip install psycopg2-binary")
        sys.exit(1)
    
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
    
    # Set ChromaDB directory from command line if provided
    if args.chroma_dir:
        global chroma_dir
        chroma_dir = args.chroma_dir
        log.info("Using ChromaDB directory from command line: %s", chroma_dir)
    else:
        log.info("Using default ChromaDB directory: %s", chroma_dir)
    
    # Try to create a direct connection to PostgreSQL to verify connectivity
    try:
        import psycopg2
        db_url = os.environ["DATABASE_URL"]
        log.info("Attempting direct connection to PostgreSQL...")
        
        # Extract connection details from the URL
        if db_url.startswith("postgresql://"):
            # Parse the URL
            parts = db_url.replace("postgresql://", "").split("@")
            if len(parts) == 2:
                auth, host_port_db = parts
                if ":" in auth:
                    username, password = auth.split(":")
                else:
                    username = auth
                    password = ""
                
                if "/" in host_port_db:
                    host_port, dbname = host_port_db.split("/")
                    if ":" in host_port:
                        host, port = host_port.split(":")
                        port = int(port)
                    else:
                        host = host_port
                        port = 5432
                else:
                    host = host_port_db
                    port = 5432
                    dbname = "postgres"
                
                log.info("Connecting to PostgreSQL: host=%s, port=%s, dbname=%s, user=%s", 
                         host, port, dbname, username)
                
                # Try to connect
                conn = psycopg2.connect(
                    host=host,
                    port=port,
                    dbname=dbname,
                    user=username,
                    password=password
                )
                log.info("Successfully connected to PostgreSQL")
                conn.close()
            else:
                log.warning("Could not parse DATABASE_URL, skipping direct connection test")
    except Exception as e:
        log.error("Error connecting to PostgreSQL: %s", e)
        log.error(traceback.format_exc())
    
    # Run cleanup
    try:
        cleanup_old_chats(days_threshold=args.days, dry_run=args.dry_run)
        log.info("Cleanup complete.")
    except Exception as e:
        log.error("Fatal error in cleanup_old_chats: %s", e)
        log.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main() 
