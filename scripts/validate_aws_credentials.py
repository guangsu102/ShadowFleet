"""
AWS 凭证验证脚本
用法: python scripts/validate_aws_credentials.py
从 SQLite fleet_assets 表读取已注册的 AWS 账号凭证进行验证。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from database.asset_models import AssetRecord
from database.asset_repo import AssetRepo
from services.runtime_service import build_runtime_context


def validate_aws_credential(
    asset_name: str, access_key: str, secret_key: str, region: str
) -> dict:
    result = {
        "asset_name": asset_name,
        "access_key_id": access_key,
        "secret_access_key": "***",
        "region": region,
        "valid": False,
        "account_id": None,
        "arn": None,
        "user_id": None,
        "error": None,
    }

    try:
        client = boto3.client(
            "sts",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        identity = client.get_caller_identity()
        result["account_id"] = identity["Account"]
        result["arn"] = identity["Arn"]
        result["user_id"] = identity["UserId"]
        result["valid"] = True
    except NoCredentialsError:
        result["error"] = "NoCredentialsError: 凭证无效，请检查 AK/SK 是否正确"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", str(e))
        if code == "InvalidClientTokenId":
            result["error"] = f"InvalidClientTokenId: AK 不正确或已被删除 (Code={code})"
        elif code == "SignatureDoesNotMatch":
            result["error"] = f"SignatureDoesNotMatch: SK 不正确 (Code={code})"
        elif code == "ExpiredToken":
            result["error"] = f"ExpiredToken: 临时凭证已过期 (Code={code})"
        elif code == "AccessDenied":
            result["error"] = f"AccessDenied: 无权限，请检查 IAM 策略 (Code={code})"
        else:
            result["error"] = f"ClientError [{code}]: {msg}"
    except Exception as e:
        result["error"] = f"UnexpectedError: {type(e).__name__}: {e}"

    return result


def test_ec2_list_regions(access_key: str, secret_key: str, region: str) -> bool:
    try:
        client = boto3.client(
            "ec2",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        client.describe_regions(AllRegions=False, MaxResults=5)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        print(f"  [EC2 Region Test] FAILED: [{code}] {msg}")
        return False
    except Exception as e:
        print(f"  [EC2 Region Test] FAILED: {type(e).__name__}: {e}")
        return False


def test_ec2_describe_instances(access_key: str, secret_key: str, region: str) -> dict:
    try:
        client = boto3.client(
            "ec2",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        resp = client.describe_instances(MaxResults=5)
        instance_count = 0
        for reservation in resp.get("Reservations", []):
            instance_count += len(reservation.get("Instances", []))
        return {"success": True, "instance_count": instance_count}
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        return {"success": False, "error": f"[{code}] {msg}"}
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}


def mask_key(key: str) -> str:
    if not key or len(key) <= 8:
        return "***"
    return f"{key[:4]}***{key[-4:]}"


def list_aws_assets(asset_repo: AssetRepo) -> list[AssetRecord]:
    with asset_repo._sqlite_manager.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM fleet_assets WHERE asset_type = 'aws' ORDER BY id ASC"
        ).fetchall()
    from database.asset_repo_helpers import map_asset_record
    return [map_asset_record(row) for row in rows]


def main() -> None:
    config_path = Path(__file__).parent.parent / "config.yaml"

    print("=" * 70)
    print("ShadowFleet AWS 凭证验证")
    print("=" * 70)
    print(f"配置文件: {config_path}")
    print()

    runtime_context = build_runtime_context(str(config_path))
    asset_repo = AssetRepo(runtime_context)

    assets = list_aws_assets(asset_repo)

    if not assets:
        print("[INFO] SQLite fleet_assets 表中未找到任何 AWS 账号")
        print()
        print("请先通过 Dashboard UI 添加 AWS 账号，每个账号的 AK/SK 将存储在本地 SQLite 中。")
        return

    aws_accounts: dict[str, dict[str, str]] = {}
    for asset in assets:
        if asset.aws_account_id and asset.aws_access_key and asset.aws_secret_key:
            key = f"{asset.aws_account_id}/{asset.region}"
            if key not in aws_accounts:
                aws_accounts[key] = {
                    "asset_name": asset.asset_name,
                    "aws_account_id": asset.aws_account_id,
                    "region": asset.region or "ap-northeast-1",
                    "access_key": asset.aws_access_key,
                    "secret_key": asset.aws_secret_key,
                }

    if not aws_accounts:
        print("[INFO] 未找到包含有效 AK/SK 的 AWS 账号")
        return

    for idx, (key, cred) in enumerate(aws_accounts.items()):
        print(f"[{idx+1}] 账号: {cred['aws_account_id']} / {cred['region']}")
        print(f"    Asset:     {cred['asset_name']}")
        print(f"    Access Key: {mask_key(cred['access_key'])}")
        print(f"    Secret Key:  {'*' * 20}")
        print(f"    Region:     {cred['region']}")
        print()

        result = validate_aws_credential(
            cred["asset_name"],
            cred["access_key"],
            cred["secret_key"],
            cred["region"],
        )

        if result["valid"]:
            print("  [OK] STS GetCallerIdentity 验证通过")
            print(f"      Account ID: {result['account_id']}")
            print(f"      ARN:        {result['arn']}")
            print(f"      User ID:    {result['user_id']}")
            print()
            print("  [TEST] EC2 列出区域权限...")
            ec2_ok = test_ec2_list_regions(
                cred["access_key"], cred["secret_key"], cred["region"]
            )
            if ec2_ok:
                print("  [OK] EC2 列出区域权限正常")
            print()
            print("  [TEST] EC2 读取实例列表...")
            ec2_result = test_ec2_describe_instances(
                cred["access_key"], cred["secret_key"], cred["region"]
            )
            if ec2_result["success"]:
                print(
                    f"  [OK] EC2 读取实例列表正常，当前区域实例数: {ec2_result['instance_count']}"
                )
            else:
                print(f"  [WARN] EC2 读取实例列表失败: {ec2_result['error']}")
        else:
            print("  [FAIL] STS GetCallerIdentity 验证失败")
            print(f"      错误原因: {result['error']}")

        print()
        print("-" * 70)
        print()

    print("验证完成。")


if __name__ == "__main__":
    main()
