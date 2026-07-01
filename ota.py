import gc
import urequests
import os
import json
import machine
from time import sleep
from log import logger

def dprint(*args):
    logger.debug(*args)

class OTAUpdater:
    """ This class handles OTA updates. It checks for updates (using version number),
        then downloads and installs multiple filenames, separated by commas."""

    def __init__(self, repo_url, *filenames):
        
        if "www.github.com" in repo_url :
            dprint(f"Updating {repo_url} to raw.githubusercontent")
            self.repo_url = repo_url.replace("www.github","raw.githubusercontent")
        elif "github.com" in repo_url:
            dprint(f"Updating {repo_url} to raw.githubusercontent'")
            self.repo_url = repo_url.replace("github","raw.githubusercontent")            
        self.version_url = self.repo_url + 'version.json'
        dprint(f"version url is: {self.version_url}")
        self.filename_list = [filename for filename in filenames]

        # get the current version (stored in version.json)
        if 'version.json' in os.listdir():    
            with open('version.json') as f:
                self.current_version = int(json.load(f)['version'])
            dprint(f"Current device firmware version is '{self.current_version}'")

        else:
            self.current_version = 0
            # save the current version
            with open('version.json', 'w') as f:
                json.dump({'version': self.current_version}, f)

    def fetch_new_code(self, filename):
        """ Fetch the code from the repo, returns False if not found or if network fails."""
        gc.collect()
        # Fetch the latest code from the repo.
        self.firmware_url = self.repo_url + filename
        count = 0
        
        for char in filename:
            if char == "/":
                count += 1
        
        if count == 1:
            prefix1 = filename.split("/")[0]
            filename = filename.split("/")[1]
            if not prefix1 in os.listdir():
                os.mkdir(prefix1)
            os.chdir(prefix1)
            
        if count == 2:
            prefix1 = filename.split("/")[0]
            prefix2 = filename.split("/")[1]
            filename = filename.split("/")[2]
            os.chdir(prefix1)
            if not prefix2 in os.listdir():
                os.mkdir(prefix2)
            os.chdir(prefix2)

        if count == 3:
            prefix1 = filename.split("/")[0]
            prefix2 = filename.split("/")[1]
            prefix3 = filename.split("/")[2]
            os.chdir(prefix1)
            os.chdir(prefix2)
            filename = filename.split("/")[3]
            if not prefix3 in os.listdir():
               os.mkdir(prefix3)
            os.chdir(prefix3)
            
        try:
            response = urequests.get(self.firmware_url)
            if response.status_code == 200:
                # Save the fetched code to file (with prepended '_')
                new_code = response.text
                with open(f'_{filename}', 'w') as f:
                    f.write(new_code)
                
                if not os.getcwd() == "/":
                    os.chdir("/")
                dprint(f'Fetched file {filename}, status: {response.status_code}')
                return True
            
            elif response.status_code == 404:
                dprint(f'Firmware not found - {self.firmware_url}.')
                if not os.getcwd() == "/":
                    os.chdir("/")
                return False
                
        except Exception as e:
            dprint(f"Network error trying to fetch {filename}: {e}")
            # Ensure we navigate back to root directory so future updates don't break
            if not os.getcwd() == "/":
                os.chdir("/")
            return False

    def check_for_updates(self):
        """ Check if updates are available. Returns False if check fails or no update found."""
        gc.collect()
        dprint(f'Checking for latest version... on {self.version_url}')
        
        try:
            response = urequests.get(self.version_url)
            data = json.loads(response.text)
            
            dprint(f"data is: {data}, url is: {self.version_url}")
            dprint(f"data version is: {data['version']}")
            
            self.latest_version = int(data['version'])
            dprint(f'latest version is: {self.latest_version}')
            
            # compare versions
            newer_version_available = True if self.current_version < self.latest_version else False
            dprint(f'Newer version available: {newer_version_available}')    
            return newer_version_available
            
        except Exception as e:
            dprint(f"Failed to check for updates due to network/JSON error: {e}")
            return False
    
    def download_and_install_update_if_available(self):
        """ Check for updates, download and install them."""
        gc.collect()
        if self.check_for_updates():

            # Fetch new code
            for filename in self.filename_list:
                self.fetch_new_code(filename)
            
            # Overwrite current code with new
            for filename in self.filename_list:
                count = 0
                for char in filename:
                    if char == "/":
                        count += 1
            
                if count == 1:
                    prefix1 = filename.split("/")[0]
                    os.chdir(prefix1)
                    filename = filename.split("/")[1]
                    
                if count == 2:
                    prefix2 = filename.split("/")[1]
                    os.chdir(prefix1)
                    os.chdir(prefix2)
                    filename = filename.split("/")[2]
                    
                if count == 3:
                    prefix3 = filename.split("/")[2]
                    os.chdir(prefix1)
                    os.chdir(prefix2)
                    os.chdir(prefix3)
                    filename = filename.split("/")[3]
                    
                newfile = f"_{filename}"
                
                # Check if the file actually downloaded before trying to rename it
                if newfile in os.listdir():
                    os.rename(newfile, filename)
                    dprint(f'Renamed _{filename} to {filename}, overwriting existing file')
                else:
                    dprint(f'Warning: Expected {newfile} was not found, skipping installation for this file.')
                
                if not os.getcwd() == "/":
                    os.chdir("/")
            
            # save the current version
            with open('version.json', 'w') as f:
                json.dump({'version': self.latest_version}, f)
            dprint(f'Update version from {self.current_version} to {self.latest_version}')

            # Restart the device to run the new code.
            dprint('Restarting device...')
            sleep(0.3)
            machine.reset() 
        else:
            dprint('No new updates available.')
