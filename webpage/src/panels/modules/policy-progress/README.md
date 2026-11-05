# policy-progress

功能契约与验收：[公司公告与政策进程](../../../../../docs/official-disclosures-panels.md)。

本目录拥有 UI、model、styles；共享 Runtime、数据校验与标题控件在 panels/shared/official-disclosures。后端独立注册模块 scripts/api/runtime_panels/modules/policy_progress.py，数据拥有者 official_disclosures_service，由 official_disclosures_watcher 定时写入 SnapshotStore。GET 不采集。
