"""Optional private S3 archive. Credentials come from the standard AWS credential chain."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import time
from server import Archive, RETENTION

PREFIX = 'jarvis/raw/'


def read_config(root):
    path = Path(root) / 'aws.json'
    if not path.exists():
        raise ValueError('AWS is not configured. Create jarvis-data/aws.json using aws/config.example.json.')
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if set(config) - {'bucket', 'region', 'profile'} or not config.get('bucket') or not config.get('region'):
        raise ValueError('AWS config requires bucket and region; optional profile. Never put credentials in this file.')
    return config


def client_for(config):
    import truststore
    truststore.inject_into_ssl()
    import boto3
    from botocore.config import Config
    return boto3.Session(profile_name=config.get('profile'), region_name=config['region']).client(
        's3', config=Config(connect_timeout=10, read_timeout=30, retries={'max_attempts': 3, 'mode': 'standard'}))


def verify_bucket(client, bucket):
    """Require a private unversioned bucket, so expiration really removes raw objects."""
    if client.get_bucket_versioning(Bucket=bucket).get('Status') in ('Enabled', 'Suspended'):
        raise ValueError('Use a dedicated bucket that has never had versioning enabled.')
    block = client.get_public_access_block(Bucket=bucket)['PublicAccessBlockConfiguration']
    if not all(block.get(key) for key in ('BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets')):
        raise ValueError('Enable all four S3 Block Public Access settings.')
    rules = client.get_bucket_lifecycle_configuration(Bucket=bucket)['Rules']
    if not any(r.get('Status') == 'Enabled' and (r.get('Filter') == {'Prefix': PREFIX} or r.get('Prefix') == PREFIX)
               and r.get('Expiration', {}).get('Days') == 30 for r in rules):
        raise ValueError('The bucket needs a 30-day lifecycle rule for jarvis/raw/. Use aws/archive-stack.yaml.')


def key_for(clip_id, started):
    return f'{PREFIX}{int(started * 1000):013d}_{clip_id}.wav'


def is_missing(exc):
    return getattr(exc, 'response', {}).get('Error', {}).get('Code') in ('404', 'NoSuchKey', 'NotFound')


class CloudArchive:
    """Own upload acknowledgement, integrity checks, retry state, and capture-time expiry."""
    def __init__(self, archive, config, client):
        self.archive, self.config, self.client = archive, config, client
        self.bucket = config['bucket']

    def cycle(self):
        # Retention always takes priority over uploading a backlog.
        with self.archive.connect() as db:
            expired = db.execute('''SELECT c.id,c.object_key FROM cloud_uploads c JOIN recordings r ON r.id=c.id
                WHERE c.bucket=? AND r.started<=? AND c.state!='expired' ''', (self.bucket,time.time()-RETENTION)).fetchall()
        for clip_id, key in expired:
            try:
                self.client.delete_object(Bucket=self.bucket, Key=key)
                self.save(clip_id,key,'expired')
            except Exception as exc:
                self.save(clip_id,key,'error',type(exc).__name__)
        with self.archive.connect() as db:
            rows = db.execute('''SELECT r.id,r.started,r.digest,r.path FROM recordings r
                LEFT JOIN cloud_uploads c ON c.id=r.id AND c.bucket=?
                WHERE r.state='done' AND r.started>? AND coalesce(c.state,'')!='uploaded'
                ORDER BY r.started''', (self.bucket,time.time()-RETENTION)).fetchall()
        for clip_id, started, digest, path in rows:
            key = key_for(clip_id, started)
            try:
                # A lost PUT acknowledgement is recovered with HEAD, not another upload.
                try:
                    remote = self.client.head_object(Bucket=self.bucket, Key=key, ChecksumMode='ENABLED')
                except Exception as exc:
                    if not is_missing(exc): raise
                    remote = None
                checksum = base64.b64encode(bytes.fromhex(digest)).decode()
                if remote is None:
                    data = Path(path).read_bytes()
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError('Local recording checksum mismatch')
                    if started <= time.time()-RETENTION:
                        continue
                    self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType='audio/wav',
                        ServerSideEncryption='AES256', ChecksumSHA256=checksum,
                        Metadata={'sha256':digest,'recorded-at':str(started)})
                    remote = self.client.head_object(Bucket=self.bucket, Key=key, ChecksumMode='ENABLED')
                if remote.get('ChecksumSHA256') != checksum:
                    raise ValueError('Remote recording checksum mismatch')
                self.save(clip_id,key,'uploaded')
            except Exception as exc:
                self.save(clip_id,key,'error',type(exc).__name__)

    def save(self, clip_id, key, state, error=None):
        with self.archive.connect() as db:
            db.execute('INSERT OR REPLACE INTO cloud_uploads VALUES(?,?,?,?,?,?)',
                       (clip_id,self.bucket,key,state,error,time.time()))

    def download(self, clip_id, digest):
        with self.archive.connect() as db:
            row=db.execute("SELECT object_key FROM cloud_uploads WHERE id=? AND bucket=? AND state='uploaded'",(clip_id,self.bucket)).fetchone()
        if not row: return None
        response=self.client.get_object(Bucket=self.bucket,Key=row[0])
        stream=response['Body']
        try: data=stream.read(2_000_001)
        finally: stream.close()
        if hashlib.sha256(data).hexdigest()!=digest:
            raise ValueError('Downloaded recording checksum mismatch')
        return data


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',default='jarvis-data')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--check',action='store_true',help='Verify bucket configuration without uploading recordings')
    args=parser.parse_args()
    try:
        config=read_config(args.data)
        client=client_for(config)
        verify_bucket(client,config['bucket'])
    except Exception as exc:
        raise SystemExit(f'AWS archive not started: {type(exc).__name__}: {exc}')
    if args.check:
        print('Private bucket, versioning, and lifecycle checks passed. No recordings uploaded.')
        return
    archive=Archive(args.data)
    cloud=CloudArchive(archive,config,client)
    while True:
        cloud.cycle()
        with archive.connect() as db:
            print('AWS archive states:',db.execute('SELECT state,count(*) FROM cloud_uploads WHERE bucket=? GROUP BY state',(config['bucket'],)).fetchall(),flush=True)
        if args.once:return
        time.sleep(60)


if __name__=='__main__':main()
