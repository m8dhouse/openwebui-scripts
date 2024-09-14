# openwebui-scripts
openweb UI scripts - https://openwebui.com/

**USE AT OWN RISK!!!
**

Always backup your installation and dat afirst before trying out any of these scripts.
There might and potentially will be errors or bugs.


#cleanup.py
cleans chat and file table for chats older than 30days (checked on update date)
removes the files also from the folder

Adapt paths to your situation + days to delete

python3 cleanup.py --test N
-> this performs all actions (delete)

python3 cleanup.py --test Y
-> this logs all actions but doesn't do them

#orphan.py
cleans files that are not in use anymore. This can be beacuse the user delete a chat or document.
It checks chats and documents to see what to keep. It then removes the rest as they are considered orphans.

Adapt paths to your situation 

python3 orphan.py --test N
-> this performs all actions (delete)

python3 orphan.py --test Y
-> this logs all actions but doesn't do them

#run_script.sh
script I use to launch open WebUI

#upgrade_openweb.sh
script I use to upgrade to latest version
