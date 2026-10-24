"""Optional explicit AWS action; building/checking never calls this helper."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from deploy.build_bundle import build,ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--region',required=True);p.add_argument('--profile')
    p.add_argument('--stack',default='opencaliber')
    p.add_argument('--bucket',required=True,help='Existing private release bucket in this region')
    p.add_argument('--platform-arn',required=True,help='Supported Python AL2023 platform ARN')
    p.add_argument('--vpc-id',required=True);p.add_argument('--subnet-id',required=True)
    p.add_argument('--az',required=True);p.add_argument('--alb-subnets',required=True,help='At least two ALB subnets in distinct AZs')
    p.add_argument('--certificate-arn',required=True);p.add_argument('--public-origin',required=True)
    p.add_argument('--apply',action='store_true',help='Create/update billable resources; otherwise write a plan only')
    a=p.parse_args()
    from urllib.parse import urlsplit
    origin=urlsplit(a.public_origin)
    if origin.scheme!='https' or not origin.hostname or origin.path or origin.query or origin.fragment or origin.username:p.error('public-origin must be a bare HTTPS origin')
    path=build();key='opencaliber/'+hashlib.sha256(path.read_bytes()).hexdigest()+'.zip'
    values={'ArtifactBucket':a.bucket,'ArtifactKey':key,'PlatformArn':a.platform_arn,'VpcId':a.vpc_id,
            'SubnetId':a.subnet_id,'AvailabilityZone':a.az,'LoadBalancerSubnets':a.alb_subnets,
            'CertificateArn':a.certificate_arn,'PublicOrigin':a.public_origin}
    parameters=[{'ParameterKey':k,'ParameterValue':v} for k,v in values.items()]
    plan={'stack':a.stack,'region':a.region,'source_bundle':str(path),'parameters':values,
          'warning':'Apply creates or updates billable resources and IAM roles. No credentials are included.'}
    (ROOT/'dist/deployment-plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    if not a.apply:
        print('Plan written to dist/deployment-plan.json; AWS was not contacted.');return
    import boto3
    session=boto3.Session(profile_name=a.profile,region_name=a.region)
    ec2=session.client('ec2');subnet=ec2.describe_subnets(SubnetIds=[a.subnet_id])['Subnets'][0]
    if subnet['AvailabilityZone']!=a.az or subnet['VpcId']!=a.vpc_id:raise ValueError('Instance subnet, VPC and data-volume AZ do not match')
    alb_ids=[x.strip() for x in a.alb_subnets.split(',') if x.strip()]
    subnets=ec2.describe_subnets(SubnetIds=alb_ids)['Subnets']
    if len({x['AvailabilityZone'] for x in subnets})<2 or any(x['VpcId']!=a.vpc_id for x in subnets):raise ValueError('ALB requires subnets in the same VPC and at least two AZs')
    session.client('s3').upload_file(str(path),a.bucket,key,ExtraArgs={'ServerSideEncryption':'AES256'})
    cfn=session.client('cloudformation');template=(ROOT/'deploy/elasticbeanstalk.json').read_text()
    cfn.validate_template(TemplateBody=template)
    from botocore.exceptions import ClientError
    try:cfn.describe_stacks(StackName=a.stack);exists=True
    except ClientError as exc:
        if exc.response['Error']['Code']!='ValidationError' or 'does not exist' not in str(exc):raise
        exists=False
    kwargs=dict(StackName=a.stack,TemplateBody=template,Parameters=parameters,Capabilities=['CAPABILITY_IAM'])
    try:
        if exists:cfn.update_stack(**kwargs)
        else:cfn.create_stack(**kwargs)
    except ClientError as exc:
        if 'No updates are to be performed' in str(exc):print('No stack changes.');return
        raise
    print('Stack submitted. Monitor CloudFormation and Beanstalk events; no secret values were printed.')


if __name__=='__main__':main()
