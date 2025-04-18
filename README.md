

```markdown
# openwebui-scripts
openweb UI scripts - [https://openwebui.com/](https://openwebui.com/)

**USE AT OWN RISK!!!**

Always backup your installation and data first before trying out any of these scripts.
There might and potentially will be errors or bugs.

## cleanup.py
Cleans chat and file table for chats older than 30 days (checked on update date).
Removes the files also from the folder.

Adapt paths to your situation and days to delete.
```
```bash
python3 cleanup.py --test N
```
This performs all actions (delete).

```bash
python3 cleanup.py --test Y
```
This logs all actions but doesn't do them.

## orphan.py
Cleans files that are not in use anymore. This can be because the user deleted a chat or document.
It checks chats and documents to see what to keep. It then removes the rest as they are considered orphans.

Adapt paths to your situation.

```bash
python3 orphan.py --test N
```
This performs all actions (delete).

```bash
python3 orphan.py --test Y
```
This logs all actions but doesn't do them.

## run_script.sh
Script I use to launch open WebUI.

## upgrade_openweb.sh
Script I use to upgrade to the latest version.
```


====================
TOTALLY UNTESTED !!


1. Chat Cleanup Script (cleanup_old_chats.py)
This script removes old chat records and their associated files from the database and filesystem.
Usage:
# Basic usage (dry run mode - shows what would be deleted)
python backend/open_webui/scripts/cleanup_old_chats.py --days 15

# Actually delete chats older than 30 days
python backend/open_webui/scripts/cleanup_old_chats.py --days 30 --dry-run=false

# Specify custom database URL
python backend/open_webui/scripts/cleanup_old_chats.py --days 15 --db-url "postgresql://user:pass@host:port/db"


Options:
--days: Number of days after which chats are considered old (default: 15)
--dry-run: Run in dry run mode (default: true)
--db-url: Custom database URL


2. Orphaned Files Cleanup Script (cleanup_orphaned_files.py)
This script removes files from the uploads directory that are not referenced in the database (files, documents, or chats).
Usage:
# Basic usage (dry run mode - shows what would be deleted)
python backend/open_webui/scripts/cleanup_orphaned_files.py

# Actually delete orphaned files
python backend/open_webui/scripts/cleanup_orphaned_files.py --dry-run=false

# Specify custom uploads directory
python backend/open_webui/scripts/cleanup_orphaned_files.py --uploads-dir "/path/to/uploads"

# Specify custom database URL
python backend/open_webui/scripts/cleanup_orphaned_files.py --db-url "postgresql://user:pass@host:port/db"


Options:
--dry-run: Run in dry run mode (default: true)
--uploads-dir: Custom path to uploads directory
--db-url: Custom database URL


Log Files
Chat cleanup logs: /usr/openweb/cleanlog/cleanup_openui.log
Orphaned files logs: /usr/openweb/orphanlog/cleanup_openui_orphans.log
