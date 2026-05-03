#!/usr/bin/env bash
# =============================================================================
# ShadowFleet AWS Teardown Script
# 清理指定 AWS 账号下的所有 ShadowFleet 资源
# 用法: bash teardown_aws.sh <AWS_ACCESS_KEY> <AWS_SECRET_KEY> [REGION]
# 示例: bash teardown_aws.sh AKIA... xxxxxx us-east-1
# =============================================================================
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "用法: $0 <AWS_ACCESS_KEY> <AWS_SECRET_KEY> [REGION]"
    echo "示例: $0 AKIAIOSFODNN7EXAMPLE xxxxxx us-east-1"
    exit 1
fi

export AWS_ACCESS_KEY_ID="$1"
export AWS_SECRET_ACCESS_KEY="$2"
export AWS_DEFAULT_REGION="${3:-us-east-1}"

echo "=== ShadowFleet AWS 清理 ==="
echo "账号 ID (STS): $(aws sts get-caller-identity --query Account --output text)"
echo "Region: $AWS_DEFAULT_REGION"
echo ""

TARGET_VPC_CIDR="10.88.0.0/16"
TARGET_VPC_CIDR_V6=""

# ---------------------------------------------------------------------------
# Step 1: 找到 ShadowFleet VPC
# ---------------------------------------------------------------------------
echo "=== [1/9] 查找 ShadowFleet VPC ==="
VPC_ID=$(aws ec2 describe-vpcs \
    --filters "Name=cidr-block-association.cidr-block,Values=${TARGET_VPC_CIDR}" \
    --query 'Vpcs[0].VpcId' \
    --output text 2>/dev/null || echo "")

if [[ -z "$VPC_ID" || "$VPC_ID" == "None" ]]; then
    echo "未找到 CIDR=$TARGET_VPC_CIDR 的 VPC，跳过清理。"
    echo "=== 清理完成（无资源）==="
    exit 0
fi
echo "找到 VPC: $VPC_ID"

# ---------------------------------------------------------------------------
# Step 2: 终止所有 EC2 实例
# ---------------------------------------------------------------------------
echo ""
echo "=== [2/9] 终止 EC2 实例 ==="
INSTANCE_IDS=$(aws ec2 describe-instances \
    --filters "Name=vpc-id,Values=${VPC_ID}" "Name=instance-state-name,Values=running,pending,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' \
    --output text)

if [[ -n "$INSTANCE_IDS" && "$INSTANCE_IDS" != "None" ]]; then
    echo "终止实例: $INSTANCE_IDS"
    aws ec2 terminate-instances --instance-ids $INSTANCE_IDS --no-dry-run
    echo "等待实例终止..."
    aws ec2 wait instance-terminated --instance-ids $INSTANCE_IDS || true
    echo "实例已终止"
else
    echo "无运行中的实例"
fi

# ---------------------------------------------------------------------------
# Step 3: 删除弹性网卡 (ENI)
# ---------------------------------------------------------------------------
echo ""
echo "=== [3/9] 删除弹性网卡 (ENI) ==="
ENI_IDS=$(aws ec2 describe-network-interfaces \
    --filters "Name=vpc-id,Values=${VPC_ID}" \
    --query 'NetworkInterfaces[].NetworkInterfaceId' \
    --output text 2>/dev/null || echo "")

if [[ -n "$ENI_IDS" && "$ENI_IDS" != "None" ]]; then
    for eni in $ENI_IDS; do
        echo "删除 ENI: $eni"
        aws ec2 delete-network-interface --network-interface-id "$eni" 2>/dev/null && echo "  已删除" || echo "  删除失败或已自动清理"
    done
else
    echo "无弹性网卡需要清理"
fi

# ---------------------------------------------------------------------------
# Step 4: 删除 NAT Gateway
# ---------------------------------------------------------------------------
echo ""
echo "=== [4/9] 删除 NAT Gateway ==="
NAT_IDS=$(aws ec2 describe-nat-gateways \
    --filter "Name=vpc-id,Values=${VPC_ID}" \
    --query 'NatGateways[?State!=`deleted`].NatGatewayId' \
    --output text 2>/dev/null || echo "")

if [[ -n "$NAT_IDS" && "$NAT_IDS" != "None" ]]; then
    for nat in $NAT_IDS; do
        echo "删除 NAT Gateway: $nat"
        aws ec2 delete-nat-gateway --nat-gateway-id "$nat" 2>/dev/null
    done
    echo "等待 NAT Gateway 删除（最长 5 分钟）..."
    sleep 30
    for nat in $NAT_IDS; do
        aws ec2 wait nat-gateway-deleted --nat-gateway-ids "$nat" 2>/dev/null || true
        echo "  $nat 已删除"
    done
else
    echo "无 NAT Gateway 需要清理"
fi

# ---------------------------------------------------------------------------
# Step 5: 释放 EIP
# ---------------------------------------------------------------------------
echo ""
echo "=== [5/9] 释放弹性 IP (EIP) ==="
EIP_ALLOCATION_IDS=$(aws ec2 describe-addresses \
    --filters "Name=domain,Values=vpc" \
    --query "Addresses[?VpcId==\`$VPC_ID\`].AllocationId" \
    --output text 2>/dev/null || echo "")

if [[ -n "$EIP_ALLOCATION_IDS" && "$EIP_ALLOCATION_IDS" != "None" ]]; then
    for alloc_id in $EIP_ALLOCATION_IDS; do
        echo "释放 EIP: $alloc_id"
        aws ec2 release-address --allocation-id "$alloc_id" 2>/dev/null && echo "  已释放" || echo "  释放失败"
    done
else
    echo "无 EIP 需要清理"
fi

# ---------------------------------------------------------------------------
# Step 6: 删除安全组
# ---------------------------------------------------------------------------
echo ""
echo "=== [6/9] 删除安全组 ==="
SG_IDS=$(aws ec2 describe-security-groups \
    --filters "Name=vpc-id,Values=${VPC_ID}" \
    --query 'SecurityGroups[?GroupName!=`default`].GroupId' \
    --output text)

if [[ -n "$SG_IDS" && "$SG_IDS" != "None" ]]; then
    for sg in $SG_IDS; do
        echo "删除安全组: $sg"
        aws ec2 delete-security-group --group-id "$sg" 2>/dev/null && echo "  已删除" || echo "  删除失败（可能有依赖）"
    done
else
    echo "无自定义安全组需要清理"
fi

# ---------------------------------------------------------------------------
# Step 7: 分离并删除 Internet Gateway
# ---------------------------------------------------------------------------
echo ""
echo "=== [7/9] 删除 Internet Gateway ==="
IGW_ID=$(aws ec2 describe-internet-gateways \
    --filters "Name=attachment.vpc-id,Values=${VPC_ID}" \
    --query 'InternetGateways[0].InternetGatewayId' \
    --output text 2>/dev/null || echo "")

if [[ -n "$IGW_ID" && "$IGW_ID" != "None" ]]; then
    echo "分离 IGW: $IGW_ID"
    aws ec2 detach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID" 2>/dev/null || true
    echo "删除 IGW: $IGW_ID"
    aws ec2 delete-internet-gateway --internet-gateway-id "$IGW_ID" 2>/dev/null && echo "  已删除" || echo "  删除失败"
else
    echo "无 Internet Gateway 需要清理"
fi

# ---------------------------------------------------------------------------
# Step 8: 删除子网
# ---------------------------------------------------------------------------
echo ""
echo "=== [8/9] 删除子网 ==="
SUBNET_IDS=$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=${VPC_ID}" \
    --query 'Subnets[].SubnetId' \
    --output text)

if [[ -n "$SUBNET_IDS" && "$SUBNET_IDS" != "None" ]]; then
    for subnet in $SUBNET_IDS; do
        echo "删除子网: $subnet"
        aws ec2 delete-subnet --subnet-id "$subnet" 2>/dev/null && echo "  已删除" || echo "  删除失败"
    done
else
    echo "无子网需要清理"
fi

# ---------------------------------------------------------------------------
# Step 9: 删除 VPC
# ---------------------------------------------------------------------------
echo ""
echo "=== [9/9] 删除 VPC ==="
echo "删除 VPC: $VPC_ID"
aws ec2 delete-vpc --vpc-id "$VPC_ID" 2>/dev/null && echo "  已删除" || echo "  删除失败（检查是否有残留依赖）"

# ---------------------------------------------------------------------------
# 清理 Key Pairs (ShadowFleet 导入的)
# ---------------------------------------------------------------------------
echo ""
echo "=== [额外] 删除 ShadowFleet Key Pairs ==="
KEY_PAIR_NAMES=$(aws ec2 describe-key-pairs \
    --filters "Name=tag:CreatedBy,Values=ShadowFleet" \
    --query 'KeyPairs[].KeyName' \
    --output text 2>/dev/null || echo "")

if [[ -n "$KEY_PAIR_NAMES" && "$KEY_PAIR_NAMES" != "None" ]]; then
    for kn in $KEY_PAIR_NAMES; do
        echo "删除 Key Pair: $kn"
        aws ec2 delete-key-pair --key-name "$kn" 2>/dev/null && echo "  已删除" || echo "  删除失败"
    done
else
    echo "无 ShadowFleet Key Pairs 需要清理"
fi

echo ""
echo "=== 清理完成 ==="
echo "VPC $VPC_ID 及所有关联资源已清理。"
