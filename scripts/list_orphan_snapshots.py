import sys
import re
import boto
import os
from pprint import pprint
from datetime import date, datetime, timedelta
sys.path.append("alfajor")
from alfajor import aws_ec2


account = "default"
if len(sys.argv) > 1:
  account = sys.argv[1]

ec2 = aws_ec2.EC2(debug = True, verbose = True, account = account)

reAmi = re.compile('ami-[^ ]+')
reVol = re.compile('vol-[^ ]+')

images = {}
imagesList = []
snapshotInImageList = []
volumes = {}
volumesList = []
snapshots_no_info = {}
snapshots_no_ami = {}
snapshots_with_ami = {}
snapshots_with_vol_info = {}
count_snapshots = None

f = open('/tmp/orphan_snapshot_report_' + account + '.txt','w')

for v in ec2.get_conn().get_all_volumes():
  #pprint(v.__dict__)
  name = ""
  if 'Name' in v.tags:
    name = v.tags['Name']
  volumes[v.id] = {'status' : v.status, 'Name' : name}
  volumesList.append(v.id)

for image in ec2.get_conn().get_all_images(owners=['self']):
  #pprint(image.__dict__)
  images[image.id] = { "Name" : image.name, "description" : str(image.description)}
  imagesList.append(image.id)

all_snapshots = ec2.get_conn().get_all_snapshots(owner='self')
count_snapshots = len(all_snapshots)

#check all the snapshots
for snapshot in all_snapshots:
  #pprint(snapshot.__dict__)
  snapshotId = snapshot.id
  snpashotDescription = snapshot.description

  #amiIdResult = reAmi.findall(snapshot.description)
  #get the ami id name
  amiSearchResult = re.search(r'.* for (.*) from .*', snapshot.description, re.M|re.I)
  if amiSearchResult:
    amiIdResult = amiSearchResult.group(1)
  else:
    amiIdResult = ""
  #print "amiIdResult", amiIdResult

  #check if the ami ID really exist
  try:
      imageObject = ec2.get_conn().get_image(amiIdResult)
      #pprint(imageObject.__dict__)
      amiFound = True
  except:
      #unable to find the image
      amiFound = False

  if not amiFound: #check if more than one associated AMI (impossible) or no associated at all.
  # no AMI found
    volIdResult = reVol.findall(snapshot.description) #find associated volumes, ideally it only return one result
    try:
      volIdResultNumber = volumesList.index(snapshot.volume_id)
      volumeFound = True
    except:
      volIdResultNumber = ""
      volumeFound = False

    #print "volIdResult=", volIdResult
    #print "volIdResultNumber=", volIdResultNumber
    #print "length volIdResult=", str(len(volIdResult))

    if not volumeFound:
      snapshots_no_info[snapshotId] = {"start_time" : snapshot.start_time}
    else:
      snapshots_with_vol_info[snapshotId] = { 'vol' : snapshot.volume_id, 'info' : volumes[snapshot.volume_id], "start_time" : snapshot.start_time}

  else:
    amiId = amiIdResult
    if amiId in images:
      snapshots_with_ami[snapshotId] = { 'ami' : amiId, 'info' : images[amiId], "start_time" : snapshot.start_time}
    else:
      snapshots_no_ami[snapshotId] = { 'ami' : amiId, "start_time" : snapshot.start_time}

print("Total amis " + str(len(images)) + "\n")
print("Total snapshots " + str(count_snapshots) + "\n")

#snapshot without associated volume will be removed.
print("Total snapshots_no_info " + str(len(snapshots_no_info)) + "\n")
delete_time = datetime.utcnow() - timedelta(days=30)
for snapshotInfo in snapshots_no_info:
    print "snapshot {snapshotid} has no associated volume , will delete".format(snapshotid=snapshotInfo)
    try:
      ec2.get_conn().delete_snapshot(snapshotInfo, True)
    except:
      print sys.exc_info()[0]


print("Total snapshosts_no_ami (but has ami ref) " + str(len(snapshots_no_ami)) + "\n")
print("Total snapshosts_with_ami (ami exists) " + str(len(snapshots_with_ami)) + "\n")

#snapshot with associated volume, only delete older than 30 days
print("Total snapshosts_with_vol " + str(len(snapshots_with_vol_info)) + "\n")
delete_time = datetime.utcnow() - timedelta(days=30)
toDelete = 0
toKeep = 0
for snapshotInfo in snapshots_with_vol_info:
    for snapshot in all_snapshots:
        if snapshotInfo == snapshot.id:
            	start_time = datetime.strptime(
            		snapshot.start_time,
            		'%Y-%m-%dT%H:%M:%S.000Z'
            	)
                if start_time < delete_time:
                    print "snapshot {snapshotid} created on {snapshotdate} , to delete".format(snapshotid=snapshot.id, snapshotdate=snapshot.start_time)
                    toDelete = toDelete+1
                    try:
                      ec2.get_conn().delete_snapshot(snapshot.id, True)
                    except:
                      print sys.exc_info()[0]

                else:
                    print "snapshot {snapshotid} created on {snapshotdate} , to keep".format(snapshotid=snapshot.id, snapshotdate=snapshot.start_time)
                    toKeep = toKeep+1
print("Total snapshosts_with_vol to delete" + str(toDelete) + "\n")
print("Total snapshosts_with_vol to keep" + str(toKeep) + "\n")


test_result = count_snapshots - (len(snapshots_no_info) + len(snapshots_no_ami) + len(snapshots_with_ami) + len(snapshots_with_vol_info))
print "snapshots - snapshots not accounted for (should be 0) " + str(test_result)

def get_days(str):
  creation_date = str.split('T')[0].split('-')
  days_since_creation = (date.today() - date(int(creation_date[0]), int(creation_date[1]), int(creation_date[2]))).days
  return days_since_creation

def print_results(data):
  for key,value in data.items():
    output = str(key)
    output = output + "\t" + str(get_days(value['start_time']))
    for k,v in value.items():
      output = output + "\t" + k + "\t" + str(v)
    f.write(output + "\n")

f.write("""
**************************************************
Snapshots with missing ami
**************************************************
This is based on the ami ref in their description.
When looking up the ami it is not there.
(Orphans)
**************************************************
""")
print_results(snapshots_no_ami)

f.write("""
**************************************************
Snapshots with an ami in their description where
the ami still exists
**************************************************
""")
print_results(snapshots_with_ami)

f.write("""
**************************************************
Snapshots that were based on a volume.
Volume Could exist or not
**************************************************
""")
print_results(snapshots_with_vol_info)

f.write("""
**************************************************
Snapshots with no ami info and no volume info in
description
**************************************************
""")
print_results(snapshots_no_info)
