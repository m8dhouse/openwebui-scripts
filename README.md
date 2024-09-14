

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
