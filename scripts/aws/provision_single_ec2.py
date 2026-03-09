#!/usr/bin/env python3
"""Provision AWS resources for a single-node Nifty AI Trader deployment."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError


def ensure_ecr_repository(ecr: Any, name: str) -> str:
    try:
        response = ecr.describe_repositories(repositoryNames=[name])
        return response["repositories"][0]["repositoryUri"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "RepositoryNotFoundException":
            raise
    response = ecr.create_repository(
        repositoryName=name,
        imageScanningConfiguration={"scanOnPush": True},
    )
    return response["repository"]["repositoryUri"]


def get_default_network(ec2: Any) -> tuple[str, str]:
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise RuntimeError("No default VPC found")
    vpc_id = vpcs[0]["VpcId"]

    subnets = ec2.describe_subnets(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "default-for-az", "Values": ["true"]},
        ]
    )["Subnets"]
    if not subnets:
        raise RuntimeError("No default subnet found in default VPC")
    subnet_id = sorted(subnets, key=lambda subnet: subnet["AvailabilityZone"])[0]["SubnetId"]
    return vpc_id, subnet_id


def ensure_security_group(ec2: Any, vpc_id: str, group_name: str) -> str:
    groups = ec2.describe_security_groups(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "group-name", "Values": [group_name]},
        ]
    )["SecurityGroups"]
    if groups:
        group_id = groups[0]["GroupId"]
    else:
        group_id = ec2.create_security_group(
            GroupName=group_name,
            Description="Nifty AI Trader single-node deployment",
            VpcId=vpc_id,
            TagSpecifications=[
                {
                    "ResourceType": "security-group",
                    "Tags": [{"Key": "Name", "Value": group_name}],
                }
            ],
        )["GroupId"]

    desired_permissions = [
        {
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 80,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "HTTP"}],
            "Ipv6Ranges": [{"CidrIpv6": "::/0", "Description": "HTTP"}],
        },
        {
            "IpProtocol": "tcp",
            "FromPort": 443,
            "ToPort": 443,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "HTTPS"}],
            "Ipv6Ranges": [{"CidrIpv6": "::/0", "Description": "HTTPS"}],
        },
    ]
    try:
        ec2.authorize_security_group_ingress(GroupId=group_id, IpPermissions=desired_permissions)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "InvalidPermission.Duplicate":
            raise
    return group_id


def ensure_instance_profile(iam: Any, prefix: str) -> tuple[str, str]:
    role_name = f"{prefix}-ec2-role"
    profile_name = f"{prefix}-ec2-profile"
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    try:
        iam.get_role(RoleName=role_name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="SSM role for Nifty AI Trader EC2 host",
            Tags=[{"Key": "Name", "Value": role_name}],
        )

    attached = iam.list_attached_role_policies(RoleName=role_name)["AttachedPolicies"]
    arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    if not any(policy["PolicyArn"] == arn for policy in attached):
        iam.attach_role_policy(RoleName=role_name, PolicyArn=arn)

    try:
        profile = iam.get_instance_profile(InstanceProfileName=profile_name)["InstanceProfile"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_instance_profile(InstanceProfileName=profile_name, Tags=[{"Key": "Name", "Value": profile_name}])
        profile = iam.get_instance_profile(InstanceProfileName=profile_name)["InstanceProfile"]

    roles = profile["Roles"]
    if not any(role["RoleName"] == role_name for role in roles):
        try:
            iam.add_role_to_instance_profile(InstanceProfileName=profile_name, RoleName=role_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "LimitExceeded":
                raise

    # IAM instance-profile propagation is eventually consistent.
    time.sleep(10)
    profile = iam.get_instance_profile(InstanceProfileName=profile_name)["InstanceProfile"]
    return profile_name, profile["Arn"]


def ensure_elastic_ip(ec2: Any, prefix: str) -> tuple[str, str]:
    target_name = f"{prefix}-eip"
    addresses = ec2.describe_addresses()["Addresses"]
    for address in addresses:
        for tag in address.get("Tags", []):
            if tag["Key"] == "Name" and tag["Value"] == target_name:
                return address["AllocationId"], address["PublicIp"]

    response = ec2.allocate_address(Domain="vpc", TagSpecifications=[
        {
            "ResourceType": "elastic-ip",
            "Tags": [{"Key": "Name", "Value": target_name}],
        }
    ])
    return response["AllocationId"], response["PublicIp"]


def latest_amazon_linux_ami(ssm: Any) -> str:
    return ssm.get_parameter(
        Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64"
    )["Parameter"]["Value"]


def ensure_instance(
    ec2: Any,
    *,
    prefix: str,
    ami_id: str,
    subnet_id: str,
    security_group_id: str,
    instance_profile_arn: str,
    instance_type: str,
    volume_size: int,
) -> str:
    name = f"{prefix}-ec2"
    reservations = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [name]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
        ]
    )["Reservations"]
    for reservation in reservations:
        for instance in reservation["Instances"]:
            instance_id = instance["InstanceId"]
            state = instance["State"]["Name"]
            if state == "stopped":
                ec2.start_instances(InstanceIds=[instance_id])
            return instance_id

    user_data = """#!/bin/bash
set -euxo pipefail
dnf update -y
dnf install -y docker
fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
systemctl enable docker
systemctl start docker
if ! docker compose version >/dev/null 2>&1; then
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi
usermod -aG docker ec2-user
mkdir -p /home/ec2-user/nifty-ai-trader
chown -R ec2-user:ec2-user /home/ec2-user/nifty-ai-trader
"""

    response = ec2.run_instances(
        ImageId=ami_id,
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        SubnetId=subnet_id,
        SecurityGroupIds=[security_group_id],
        IamInstanceProfile={"Arn": instance_profile_arn},
        UserData=user_data,
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/xvda",
                "Ebs": {
                    "VolumeSize": volume_size,
                    "VolumeType": "gp3",
                    "DeleteOnTermination": True,
                },
            }
        ],
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": name}],
            }
        ],
    )
    return response["Instances"][0]["InstanceId"]


def associate_elastic_ip(ec2: Any, allocation_id: str, instance_id: str) -> None:
    addresses = ec2.describe_addresses(AllocationIds=[allocation_id])["Addresses"]
    if not addresses:
        raise RuntimeError("Elastic IP allocation not found")
    address = addresses[0]
    if address.get("InstanceId") == instance_id:
        return
    if "AssociationId" in address:
        ec2.disassociate_address(AssociationId=address["AssociationId"])
    ec2.associate_address(AllocationId=allocation_id, InstanceId=instance_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="ap-south-1")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--prefix", default="nifty-ai-trader")
    parser.add_argument("--backend-repo", default="nifty-ai-backend")
    parser.add_argument("--frontend-repo", default="nifty-ai-frontend")
    parser.add_argument("--instance-type", default="t3.medium")
    parser.add_argument("--volume-size", type=int, default=30)
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    ecr = session.client("ecr")
    ec2 = session.client("ec2")
    iam = session.client("iam")
    ssm = session.client("ssm")

    backend_uri = ensure_ecr_repository(ecr, args.backend_repo)
    frontend_uri = ensure_ecr_repository(ecr, args.frontend_repo)
    vpc_id, subnet_id = get_default_network(ec2)
    security_group_id = ensure_security_group(ec2, vpc_id, f"{args.prefix}-sg")
    profile_name, profile_arn = ensure_instance_profile(iam, args.prefix)
    allocation_id, public_ip = ensure_elastic_ip(ec2, args.prefix)
    ami_id = latest_amazon_linux_ami(ssm)
    instance_id = ensure_instance(
        ec2,
        prefix=args.prefix,
        ami_id=ami_id,
        subnet_id=subnet_id,
        security_group_id=security_group_id,
        instance_profile_arn=profile_arn,
        instance_type=args.instance_type,
        volume_size=args.volume_size,
    )

    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=[instance_id])
    associate_elastic_ip(ec2, allocation_id, instance_id)

    print(
        json.dumps(
            {
                "region": args.region,
                "backend_repository_uri": backend_uri,
                "frontend_repository_uri": frontend_uri,
                "vpc_id": vpc_id,
                "subnet_id": subnet_id,
                "security_group_id": security_group_id,
                "instance_profile": profile_name,
                "instance_profile_arn": profile_arn,
                "instance_id": instance_id,
                "elastic_ip_allocation_id": allocation_id,
                "public_ip": public_ip,
                "ami_id": ami_id,
                "instance_type": args.instance_type,
                "volume_size": args.volume_size,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
