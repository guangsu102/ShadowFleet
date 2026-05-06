@echo off
cd /d D:\tanxuan\project\ShadowFleet
git add scripts/userdata_original.sh scripts/userdata_test_iptables_callback.sh
git -c commit.gpgsign=false commit -m "fix(scripts): fix log permission and debconf lock race in user_data scripts"
git -c commit.gpgsign=false push
