"""Retained EBS mount adapted from Impact Studio; no forced detach or overwrite."""
import json,os,re,subprocess,time,urllib.request
from pathlib import Path
MOUNT=Path('/mnt/opencaliber')

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def request(url, method='GET', data=None, timeout=10, headers=None):
    body=None if data is None else json.dumps(data).encode()
    req=urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())

def environment():
    values=json.loads(run('/opt/elasticbeanstalk/bin/get-config', 'environment'))
    os.environ.update({k:str(v) for k,v in values.items()})
    return values

def identity():
    req=urllib.request.Request('http://169.254.169.254/latest/api/token', method='PUT', headers={'X-aws-ec2-metadata-token-ttl-seconds':'60'})
    with urllib.request.urlopen(req, timeout=5) as response: token=response.read().decode()
    return request('http://169.254.169.254/latest/dynamic/instance-identity/document', headers={'X-aws-ec2-metadata-token':token})

def volume_device(volume_id, attachment_device='/dev/sdf'):
    serial=volume_id.replace('-', '')
    devices=json.loads(run('lsblk','--json','--output','PATH,SERIAL,TYPE'))['blockdevices']
    for device in devices:
        if device.get('type')=='disk' and (device.get('serial') or '').replace('-', '')==serial:
            return device['path']
    # Xen-backed instances expose the device from the verified EBS attachment.
    xen=attachment_device.replace('/dev/sd','/dev/xvd')
    if Path(xen).exists(): return xen
    raise RuntimeError('Attached data volume block device is not visible yet')

def mount_volume(config, instance, ec2, sleep=time.sleep):
    volume_id=config.get('OPENCALIBER_DATA_VOLUME_ID','')
    if not re.fullmatch(r'vol-[0-9a-f]+',volume_id):
        raise RuntimeError('OPENCALIBER_DATA_VOLUME_ID must name the retained EBS volume')
    attached=False
    for _ in range(120):
        volume=ec2.describe_volumes(VolumeIds=[volume_id])['Volumes'][0]
        if volume['AvailabilityZone']!=instance['availabilityZone']:
            raise RuntimeError('Data volume and EC2 instance must be in the same availability zone')
        attachments=volume.get('Attachments',[])
        if attachments:
            attachment=attachments[0]
            if attachment['InstanceId']==instance['instanceId'] and attachment['State']=='attached':
                attached=True; break
            # Never force-detach live SQLite storage from another instance.
            if _ % 12 == 0: print('Waiting for previous instance to release retained data volume',flush=True)
        elif volume['State']=='available':
            ec2.attach_volume(VolumeId=volume_id, InstanceId=instance['instanceId'], Device='/dev/sdf')
        sleep(5)
    if not attached: raise RuntimeError('Retained volume unavailable; no force detach was attempted')
    for attempt in range(20):
        try: device=volume_device(volume_id,attachment.get('Device','/dev/sdf')); break
        except RuntimeError:
            if attempt==19: raise
            sleep(2)
    filesystem=subprocess.run(['blkid','-s','TYPE','-o','value',device],capture_output=True,text=True)
    if filesystem.returncode==2:
        tags={tag['Key']:tag['Value'] for tag in volume.get('Tags',[])}
        if tags.get('OpenCaliberStorageState')!='fresh':
            raise RuntimeError('Refusing to format previously initialized or unmanaged storage')
        # Only a volume positively identified by its EBS ID may be initialized.
        if run('lsblk','--noheadings','--output','TYPE',device).splitlines()!=['disk']:
            raise RuntimeError('Refusing to initialize a volume with partitions')
        run('mkfs.ext4','-F','-L','opencaliber-data',device)
    elif filesystem.returncode!=0 or filesystem.stdout.strip()!='ext4':
        raise RuntimeError('Retained volume must use ext4; no existing filesystem was overwritten')
    ec2.create_tags(Resources=[volume_id],Tags=[{'Key':'OpenCaliberStorageState','Value':'initialized'}])
    MOUNT.mkdir(parents=True,exist_ok=True)
    if not os.path.ismount(MOUNT): run('mount',device,str(MOUNT))
    expected=run('blkid','-s','UUID','-o','value',device)
    source=run('findmnt','--noheadings','--output','SOURCE','--target',str(MOUNT))
    if run('blkid','-s','UUID','-o','value',source)!=expected:
        raise RuntimeError('Mount point contains a different volume')
    fstab=Path('/etc/fstab'); entry=f'UUID={expected} {MOUNT} ext4 defaults,nofail 0 2'
    lines=[line for line in fstab.read_text().splitlines() if ' /mnt/opencaliber ' not in line]
    fstab.write_text('\n'.join(lines+[entry])+'\n')
    data=MOUNT/'data'; data.mkdir(exist_ok=True)
    run('chown','webapp:webapp',str(data)); run('chmod','750',str(data))


def main():
    config=environment()
    mode=config.get('OPENCALIBER_STORAGE_MODE','retained')
    if mode=='retained':
        if not re.fullmatch(r'vol-[0-9a-f]+',config.get('OPENCALIBER_DATA_VOLUME_ID','')):
            raise RuntimeError('Retained mode requires OPENCALIBER_DATA_VOLUME_ID')
        import boto3
        instance=identity()
        mount_volume(config,instance,boto3.client('ec2',region_name=instance['region']))
    elif mode=='instance':
        data=MOUNT/'data';data.mkdir(parents=True,exist_ok=True)
        run('chown','webapp:webapp',str(data));run('chmod','750',str(data))
        print('Instance storage selected explicitly; replacement loses evaluation history.')
    else:raise RuntimeError('Storage mode must be retained or instance')
    print('OpenCaliber data directory prepared.')

if __name__=='__main__':main()
