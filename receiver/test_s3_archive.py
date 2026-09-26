import base64
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
import types
from unittest.mock import patch
from server import Archive,RETENTION
from s3_archive import CloudArchive,verify_bucket,key_for
from test_server import audio


class Missing(Exception):
    response={'Error':{'Code':'404'}}


class FakeS3:
    def __init__(self):
        self.objects={};self.puts=0;self.fail_put_ack=False;self.fail_delete=False;self.corrupt=False
    def get_bucket_versioning(self,**kw):return {}
    def get_public_access_block(self,**kw):return {'PublicAccessBlockConfiguration':dict.fromkeys(('BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets'),True)}
    def get_bucket_lifecycle_configuration(self,**kw):return {'Rules':[{'Status':'Enabled','Filter':{'Prefix':'jarvis/raw/'},'Expiration':{'Days':30}}]}
    def head_object(self,**kw):
        if kw['Key'] not in self.objects:raise Missing()
        obj=self.objects[kw['Key']]
        return {'ChecksumSHA256':'bad' if self.corrupt else obj['ChecksumSHA256']}
    def put_object(self,**kw):
        self.puts+=1;self.objects[kw['Key']]=kw
        if self.fail_put_ack:raise TimeoutError()
        return {}
    def delete_object(self,**kw):
        if self.fail_delete:raise TimeoutError()
        self.objects.pop(kw['Key'],None)
        return {}
    def get_object(self,**kw):return {'Body':io.BytesIO(self.objects[kw['Key']]['Body'])}


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.archive=Archive(self.temp.name)
        self.client=FakeS3();self.config={'bucket':'test-private-bucket','region':'ap-northeast-1'}
        self.cloud=CloudArchive(self.archive,self.config,self.client)
        self.clip=str(uuid.uuid4());self.started=time.time()
        self.archive.ingest(self.clip,self.started,audio())
        with self.archive.connect() as db:db.execute("UPDATE recordings SET state='done',transcript='Test' WHERE id=?",(self.clip,))
    def tearDown(self):self.temp.cleanup()
    def state(self):
        with self.archive.connect() as db:return db.execute('SELECT state FROM cloud_uploads WHERE id=?',(self.clip,)).fetchone()[0]
    def test_verified_upload_is_private_encrypted_and_idempotent(self):
        verify_bucket(self.client,self.config['bucket'])
        self.cloud.cycle();self.cloud.cycle()
        self.assertEqual(self.client.puts,1);self.assertEqual(self.state(),'uploaded')
        obj=next(iter(self.client.objects.values()))
        self.assertEqual(obj['ServerSideEncryption'],'AES256');self.assertNotIn('ACL',obj)
        self.assertEqual(obj['Body'],audio())
    def test_lost_ack_recovered_without_duplicate_put(self):
        self.client.fail_put_ack=True;self.cloud.cycle()
        self.assertEqual(self.state(),'error')
        self.cloud.cycle()
        self.assertEqual(self.state(),'uploaded');self.assertEqual(self.client.puts,1)
    def test_checksum_mismatch_is_not_acknowledged(self):
        self.client.corrupt=True;self.cloud.cycle()
        self.assertEqual(self.state(),'error')
        self.assertTrue((self.archive.raw/(self.clip+'.wav')).exists())
    def test_expiration_retry_keeps_transcript(self):
        self.cloud.cycle()
        with self.archive.connect() as db:db.execute('UPDATE recordings SET started=?',(time.time()-RETENTION-1,))
        self.client.fail_delete=True;self.cloud.cycle();self.assertEqual(self.state(),'error')
        self.client.fail_delete=False;self.cloud.cycle();self.assertEqual(self.state(),'expired')
        self.assertFalse(self.client.objects)
        self.assertEqual(self.archive.search('Test')[0]['transcript'],'Test')
    def test_local_corruption_not_uploaded(self):
        (self.archive.raw/(self.clip+'.wav')).write_bytes(b'broken')
        self.cloud.cycle();self.assertEqual(self.client.puts,0);self.assertEqual(self.state(),'error')
    def test_cloud_playback_when_local_copy_missing(self):
        self.cloud.cycle()
        (self.archive.raw/(self.clip+'.wav')).unlink()
        (self.archive.root/'aws.json').write_text(json.dumps(self.config))
        with patch('s3_archive.client_for',return_value=self.client):
            self.assertEqual(self.archive.audio(self.clip),audio())
    def test_versioned_and_public_bucket_rejected(self):
        with patch.object(self.client,'get_bucket_versioning',return_value={'Status':'Enabled'}):
            with self.assertRaises(ValueError):verify_bucket(self.client,self.config['bucket'])
        with patch.object(self.client,'get_public_access_block',return_value={'PublicAccessBlockConfiguration':{}}):
            with self.assertRaises(ValueError):verify_bucket(self.client,self.config['bucket'])
    def test_old_unuploaded_clip_is_not_sent(self):
        with self.archive.connect() as db:db.execute('UPDATE recordings SET started=?',(time.time()-RETENTION-1,))
        self.cloud.cycle();self.assertEqual(self.client.puts,0)

    def test_actual_boto3_request_shapes(self):
        import boto3
        from botocore.stub import Stubber
        client=boto3.client('s3',region_name='ap-northeast-1',aws_access_key_id='test',aws_secret_access_key='test')
        key=key_for(self.clip,self.started)
        with self.archive.connect() as db:digest=db.execute('SELECT digest FROM recordings').fetchone()[0]
        checksum=base64.b64encode(bytes.fromhex(digest)).decode()
        head={'Bucket':self.config['bucket'],'Key':key,'ChecksumMode':'ENABLED'}
        put={'Bucket':self.config['bucket'],'Key':key,'Body':audio(),'ContentType':'audio/wav','ServerSideEncryption':'AES256',
             'ChecksumSHA256':checksum,'Metadata':{'sha256':digest,'recorded-at':str(self.started)}}
        with Stubber(client) as stub:
            stub.add_client_error('head_object',service_error_code='404',http_status_code=404,expected_params=head)
            stub.add_response('put_object',{},put)
            stub.add_response('head_object',{'ChecksumSHA256':checksum},head)
            CloudArchive(self.archive,self.config,client).cycle()
            stub.assert_no_pending_responses()
        self.assertEqual(self.state(),'uploaded')


class CleanupTests(unittest.TestCase):
    def test_deployed_cleanup_only_deletes_expired_recording_keys(self):
        import yaml
        template=yaml.load((Path(__file__).parents[1]/'aws/archive-stack.yaml').read_text(),Loader=yaml.BaseLoader)
        code=template['Resources']['ExpireRecordings']['Properties']['Code']['ZipFile']
        old=key_for(str(uuid.uuid4()),time.time()-RETENTION-10)
        new=key_for(str(uuid.uuid4()),time.time())
        unrelated='jarvis/raw/notes.txt'
        class Client:
            def get_paginator(self,name):return self
            def paginate(self,**kw):return [{'Contents':[{'Key':key} for key in [old,new,unrelated]]}]
            def delete_objects(self,**kw):self.deleted=kw['Delete']['Objects'];return {}
        client=Client();scope={}
        with patch.dict('sys.modules',{'boto3':types.SimpleNamespace(client=lambda service:client)}),patch.dict('os.environ',{'BUCKET':'test-bucket'}):
            exec(compile(code,'cleanup-lambda','exec'),scope)
            self.assertEqual(scope['handler']({},None),{'deleted':1})
        self.assertEqual(client.deleted,[{'Key':old}])


if __name__=='__main__':unittest.main()
