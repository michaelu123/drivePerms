import os
import json
import openpyxl

import google.auth.transport.requests
from google.oauth2.credentials import Credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/drive.metadata",
]


class GDrivePerms:
    def __init__(self):
        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(google.auth.transport.requests.Request())
            else:
                flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        try:
            self.service = googleapiclient.discovery.build('drive', 'v3', credentials=creds)
        except HttpError as error:
            print(f'An error occurred: {error}')

    def addRow(self, path, type, role, email):
        if email is None:
            email = "_" + type
        self.ws.append([path, type, role, email])

    def listDrives(self):
        nextPageTokenD = None
        res = []
        while True:
            results = self.service.drives().list(
                pageToken=nextPageTokenD,
                pageSize=100).execute()
            nextPageToken = results.get("nextPageToken")
            items = results.get('drives', [])
            if not items:
                return res
            res.extend(items)
            if nextPageToken is None:
                break
        return res

    def listRootLevelFiles(self, driveId):
        nextPageToken = None
        res = []
        while True:
            if driveId is None:
                root = self.service.files().get(fileId="root", fields="*").execute()
                self.myDriveOwner = root["owners"][0]["emailAddress"]
                results = self.service.files().list(
                    pageToken=nextPageToken,
                    q="'root' in parents",
                    pageSize=100).execute()
            else:
                results = self.service.files().list(
                    driveId=driveId,
                    includeItemsFromAllDrives=True, corpora="drive", supportsAllDrives=True, spaces="drive",
                    pageToken=nextPageToken,
                    q=f"'{driveId}' in parents",
                    pageSize=100).execute()
            nextPageToken = results.get("nextPageToken")
            items = results.get('files', [])
            if items:
                res.extend(items)
            if nextPageToken is None:
                break
        return res

    def listFilesInDir(self, fileId):
        nextPageToken = None
        res = []
        while True:
            results = self.service.files().list(
                pageToken=nextPageToken,
                q=f"'{fileId}' in parents",
                pageSize=100).execute()
            nextPageToken = results.get("nextPageToken")
            items = results.get('files', [])
            if items:
                res.extend(items)
            if nextPageToken is None:
                break
        return res

    def listPerms(self, fileId, indent, path):
        lines = []
        permList = self.service.permissions().list(
            fileId=fileId,
            supportsAllDrives=True,
            pageSize=100).execute()
        perms = permList["permissions"]
        for perm in perms:
            p = self.service.permissions().get(
                fileId=fileId, permissionId=perm["id"],
                fields='type,role,permissionDetails,emailAddress,allowFileDiscovery',
                supportsAllDrives=True).execute()
            assert p["type"] == perm["type"]
            assert p["role"] == perm["role"]
            # print("   XXXXXX", p)

            permDetails = p.get("permissionDetails")
            if permDetails is None: # looking at MyDrive
                if fileId != "root" and p.get("emailAddress") == self.myDriveOwner:
                    continue
            else:
                allInherited = True
                for permDetail in permDetails:
                    if not permDetail.get("inherited"):
                        allInherited = False
                        break
                if allInherited:
                    continue

            type = p["type"]
            role = p["role"]
            email = p.get('emailAddress')
            self.addRow(path, type, role, email)
            indentS = str(" " * indent)
            if type == "user":
                lines.append("User " + email + " " + role)
            elif type == "group":
                lines.append("Group " + email + " " + role)
            elif type == "domain":
                lines.append("ADFCM " + role + (" allow discovery" if p["allowFileDiscovery"] else ""))
            elif type == "anyone":
                lines.append("Anyone " + role + (" allow discovery" if p["allowFileDiscovery"] else ""))
            else:
                lines.append("TODO " + type + " " + role)
        return "\n".join([str(" " * indent) + line for line in lines])

    def listFiles(self, files, indent, path):
        for file in files:
            try:
                isDir = file['mimeType'] == "application/vnd.google-apps.folder"
                fpath = path + file['name']
                if isDir:
                    fpath += "/"
                output = self.listPerms(file["id"], indent + 3, fpath)
                if output != "":
                    print(str(" " * indent) + fpath)
                    print(output)
                if isDir:
                    subFiles = self.listFilesInDir(file["id"])
                    self.listFiles(subFiles, indent + 3, fpath)
            except Exception as e:
               print("Error", e)

    def __enter__(self):
        self.wb = openpyxl.Workbook()
        self.ws = self.wb.active
        self.ws.title = "DrivePerms"
        self.ws.freeze_panes = "A2"
        self.ws.append(["Path", "Type", "Role", "Email"])
        return self

    def __exit__(self, *args):
        self.wb.save("DrivePerms.xlsx")
        self.wb.close()

def main():
    with GDrivePerms() as gdp:
        print("MyDrive")
        files = gdp.listRootLevelFiles(None)
        print(gdp.listPerms("root", 3, "MyDrive/"))
        gdp.listFiles(files, 0, "MyDrive/")

        print()
        print()
        print('Geteilte Ablagen:')
        drives = gdp.listDrives()
        for drive in drives:
            print()
            drvName = drive["name"]
            driveId = drive["id"]
            print(drvName)
            print(gdp.listPerms(driveId, 3, drvName + "/"))
            print()
            files = gdp.listRootLevelFiles(driveId)
            gdp.listFiles(files, 3, drvName + "/")
        print()

if __name__ == '__main__':
    main()

"""
Alle:
                    deleted
My-Drive:
Type    Role
user    owner       emailAddress displayName
user    writer      emailAddress displayName
user    reader      emailAddress displayName
anyone  reader      allowFileDiscovery
anyone  writer      allowFileDiscovery
domain  reader      allowFileDiscovery
domain  writer      allowFileDiscovery

Shared:
alle                        emailAddress displayName permissionDetails
group   fileOrganizer
group   organizer
user    fileOrganizer
"""
