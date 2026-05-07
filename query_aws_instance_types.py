#!/usr/bin/env python3
"""查询 AWS API 返回的 ARM64 实例类型列表"""

import sys
import boto3
from botocore.exceptions import ClientError

def query_aws_instance_types(region_name: str = "ap-northeast-1",
                               aws_access_key: str = None,
                               aws_secret_key: str = None):
    """查询 AWS API 返回的 ARM64 实例类型"""
    try:
        if aws_access_key and aws_secret_key:
            ec2 = boto3.client(
                'ec2',
                region_name=region_name,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key
            )
        else:
            ec2 = boto3.client('ec2', region_name=region_name)

        print(f"查询区域: {region_name}")
        print("=" * 80)

        response = ec2.describe_instance_types(
            Filters=[{"Name": "processor-info.supported-architecture", "Values": ["arm64"]}]
        )

        # 收集所有 t4g 实例
        t4g_instances = []
        two_vcpu_instances = []

        for t in response.get("InstanceTypes", []):
            name = t.get("InstanceType", "")
            vcpu_info = t.get("VCpuInfo", {})
            mem_info = t.get("MemoryInfo", {})

            default_cores = vcpu_info.get("DefaultCores", 0)
            memory_mib = mem_info.get("SizeInMiB", 0)
            memory_gb = round(memory_mib / 1024, 1)

            if name.startswith("t4g"):
                t4g_instances.append({
                    'name': name,
                    'vcpu': default_cores,
                    'memory_gb': memory_gb,
                    'distance_to_2gb': abs(memory_gb - 2.0)
                })

            if default_cores == 2:
                two_vcpu_instances.append({
                    'name': name,
                    'vcpu': default_cores,
                    'memory_gb': memory_gb,
                    'distance_to_2gb': abs(memory_gb - 2.0)
                })

        print(f"总共找到 {len(response.get('InstanceTypes', []))} 个 ARM64 实例类型")
        print(f"其中 t4g 系列: {len(t4g_instances)} 个")
        print(f"其中 2 vCPU: {len(two_vcpu_instances)} 个")

        print("\n" + "=" * 80)
        print("t4g 系列实例 (按内存距离 2GB 排序):")
        print("=" * 80)
        t4g_instances.sort(key=lambda x: x['distance_to_2gb'])
        for inst in t4g_instances:
            print(f"  {inst['name']:<15} vcpu={inst['vcpu']:<3} memory={inst['memory_gb']}GB  distance_to_2gb={inst['distance_to_2gb']:.1f}")

        print("\n" + "=" * 80)
        print("2 vCPU 实例 (按内存距离 2GB 排序):")
        print("=" * 80)
        two_vcpu_instances.sort(key=lambda x: (x['distance_to_2gb'], x['name']))
        for inst in two_vcpu_instances[:20]:  # 只显示前20个
            print(f"  {inst['name']:<15} vcpu={inst['vcpu']:<3} memory={inst['memory_gb']}GB  distance_to_2gb={inst['distance_to_2gb']:.1f}")

        if len(two_vcpu_instances) > 20:
            print(f"  ... 还有 {len(two_vcpu_instances) - 20} 个实例")

        print("\n" + "=" * 80)
        print("代码会选择 (按排序 key): (vcpu, abs(memory-2.0), series_priority, name)")
        print("=" * 80)
        # 模拟代码逻辑
        def sort_key(inst):
            if inst['name'].startswith("t4g"):
                priority = 1
            elif inst['name'].startswith("c6g"):
                priority = 2
            elif inst['name'].startswith("m6g"):
                priority = 3
            else:
                priority = 9
            return (inst['vcpu'], inst['distance_to_2gb'], priority, inst['name'])

        two_vcpu_instances.sort(key=sort_key)
        best = two_vcpu_instances[0]
        print(f"会选择: {best['name']} (vcpu={best['vcpu']}, memory={best['memory_gb']}GB)")

    except ClientError as e:
        print(f"AWS API 错误: {e}")
        return False

    return True

if __name__ == "__main__":
    # 默认使用 ap-northeast-1 (东京)
    region = sys.argv[1] if len(sys.argv) > 1 else "ap-northeast-1"
    aws_access_key = sys.argv[2] if len(sys.argv) > 2 else None
    aws_secret_key = sys.argv[3] if len(sys.argv) > 3 else None

    if not aws_access_key or not aws_secret_key:
        print("提示: 可以传入 AWS credentials: python query_aws_instance_types.py <region> <access_key> <secret_key>")
        print("或者配置 AWS 环境变量/配置文件")

    query_aws_instance_types(region, aws_access_key, aws_secret_key)
