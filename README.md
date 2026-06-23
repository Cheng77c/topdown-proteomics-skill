# topdown-proteomics skill

在 **Bohrium 算力**上跑 top-down 蛋白质组学流水线(`msconvert → TopFD/FLASHDeconv → TopPIC`,以及 InformedProteomics 链)的 Shrimp/OpenClaw skill。sandbox 只做编排(校验、提交、轮询、回收),重计算在 Bohrium 作业里。

## 目录
| 路径 | 说明 |
|---|---|
| `skill/topdown-proteomics/` | **部署单元**:SKILL.md + scripts/ + references/ + examples/ + image.txt |
| `pkg/` | 镜像内执行器源(`td_cli`/`td_pipeline`/`td_derive`/`run.sh`),烤进 Bohrium 镜像 |
| `tests/` | 单元测试 |

## 部署到平台
把 `skill/topdown-proteomics/` 安装为 skill(如克隆后指向 `/data/skills/topdown-proteomics`)。必填配置(openclaw `env`/configField):
- `ACCESS_KEY`(平台亦可注入 `BOHR_ACCESS_KEY`,脚本两者都认)
- `PROJECT_ID`(无默认,必须配置)
镜像地址单一源 = `skill/topdown-proteomics/image.txt`(版本迭代只改这一处)。

## 标准流程(skill 内置铁律)
`validate_pipeline.py` →(大输入)`make_dataset.py` → `submit_pipeline.py` → `poll_job.py`(单次,不自旋)→ `collect_results.py`。

## 测试
```bash
cd <repo> && bash build-pkg.sh                 # 组装 build/(需同级 topdown_agent 包,见下)
PYTHONPATH=build python -m pytest tests/ -q
```
> 执行器测试依赖 `topdown_agent` 精简包(由 `build-pkg.sh` 从主仓 `topdown-agent` 组装);纯脚本测试(validate/submit/poll/collect)无此依赖。镜像构建在 bohr-node 上做。
