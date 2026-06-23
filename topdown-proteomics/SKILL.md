---
name: topdown-proteomics
version: 1.0.0
description: >
  在 Bohrium 算力上跑 top-down 蛋白质组学流水线(msconvert → TopFD/FLASHDeconv → TopPIC)。
  用户提供 .raw/.mzML 谱图 + 蛋白质 FASTA 库,确认参数后提交 Bohrium job,回收 PrSM/proteoform 报告。
  Use when: 用户要对 top-down 质谱数据做蛋白型鉴定 / 反卷积 / TopPIC 搜索。
  NOT for: bottom-up(肽段)搜索、纯文献/数据问答。
type: sandbox
requires:
  - bohrium-job
configFields:
  - name: IMAGE_ADDRESS
    type: text
    description: top-down 流水线镜像地址(留空则用 skill 的 image.txt;版本迭代改 image.txt 一处即可,此项仅临时覆盖)
  - name: PROJECT_ID
    type: text
    description: Bohrium 项目 ID(提交 job 所属项目;无默认,必须配置,同 ACCESS_KEY)
  - name: MACHINE_TYPE
    type: text
    description: 计算机型(top-down 用 CPU 多核即可,无需 GPU)
    default: "c16_m32_cpu"
metadata:
  openclaw:
    primaryEnv: ACCESS_KEY
l0: Top-down 蛋白质组学流水线(Bohrium)
l1: >
  用户给 .raw/.mzML + FASTA;确认质量误差/PTM/FDR 等参数后,提交 Bohrium job 跑
  msconvert→TopFD→TopPIC,产 PrSM 与 proteoform 报告并回收摘要。重计算在 Bohrium,不在 sandbox。
---

# topdown-proteomics

在 **Bohrium 计算节点**上跑 top-down 蛋白质组学流水线;sandbox 只做编排(装配、提交、轮询、回收)。

## 镜像与执行(必读,最高优先)

- **只有一个镜像**,地址的**单一源 = skill 根的 `image.txt`**(版本迭代只改这一个文件;脚本都从它读,env `IMAGE_ADDRESS` 可临时覆盖)。
  里面**已烤入全套工具 + 流水线执行器**:msconvert、TopFD、FLASHDeconv、TopPIC、InformedProteomics(均含 wine/.NET 依赖),
  执行器入口 `/opt/topdown/run.sh`(读 pipeline.json 跑链路、接线、校验)。skill 只产 pipeline.json + 取结果,不带执行器代码。
- ❌ **绝不要去 Bohrium 镜像库搜索 msconvert / TopPIC / 任何"单工具镜像"**——它们不存在,全部工具都在上面这一个镜像里。
- ❌ **绝不要自己手写 job.json、自己拼 image_address、自己调 bohr image list 找镜像。**
- ✅ **一律通过 `scripts/submit_pipeline.py` 提交**——它自动用配置的 `IMAGE_ADDRESS`、装配 pipeline.json 和上传包。
  你只需提供 spectrum / fasta / 参数;镜像与作业配置由脚本处理。
- 重二进制都在镜像里跑(经 Bohrium 作业),**不要在 sandbox 里直接跑 msconvert/TopPIC**。

如果 `IMAGE_ADDRESS`/`PROJECT_ID`/`ACCESS_KEY` 未配置,**不要猜或找替代镜像**——用 `AskUserInput` 让用户补配置或提示去启用 `bohrium-job` skill。

### 🚫 五条铁律(违反=必错)
1. **绝不手写 job.json / 绝不自己拼 `bohr job submit`** —— 一律 `scripts/submit_pipeline.py`。
2. **绝不直接调工具**(msconvert/topfd/toppic…)—— 只经 `submit_pipeline.py` 提交。
3. **大输入(.raw)先 `make_dataset.py` 再提交**;结果用 `collect_results.py` 取。
4. **取结果只用 `collect_results.py`**:**绝不手动 `bohr job download` / 解压 zip / 拷贝产物**——手动会搞出 `dl/`、`out/out/`、散落到顶层的文件等混乱。collect 已给出 `result_dir`/`deliverable_paths`/`archive`,按它给的路径用即可。
5. **标准流程不可跳**:`validate_pipeline.py` →(大输入)`make_dataset.py` → `submit_pipeline.py` → `poll_job.py` → `collect_results.py`。

## 何时用

- 用户上传了 top-down 质谱原始数据(`.raw`)或转换后的 `.mzML`,要做蛋白型(proteoform)鉴定。
- 关键词:top-down、TopPIC、TopFD、proteoform、PrSM、反卷积、完整蛋白测序。

## 环境准备(每个 Bash 调用前必做)

sandbox 每次 Bash 是独立 shell,环境变量不跨调用持久化。**第一次**用 setup.sh 落环境文件,
**之后每条命令开头**都 `source` 它:
```bash
bash scripts/setup.sh              # 装 bohr CLI + 写 /bohr-workspace/.bohr_env(只需一次)
source /bohr-workspace/.bohr_env   # 每个新 Bash 调用开头都要,确保 ACCESS_KEY/PROJECT_ID 在
```
鉴权要点:bohr CLI 认 `ACCESS_KEY` 环境变量;直接调 REST API 用 HTTP 头 `accessKey: <key>`(**不是** `Authorization: Bearer`)。脚本已按此写。

> ⛔ **只许 `bash scripts/setup.sh` 生成 .bohr_env,绝不手写/覆写它**(setup 已兜底读 `BOHR_ACCESS_KEY`)。
> - `ACCESS_KEY` 未注入:先完成授权 + 重载 skill,再 `setup.sh`(setup 跑早于授权才会读不到)。
> - `PROJECT_ID` 未注入:用 `AskUserInput` 向用户要项目 ID,**绝不硬编码**(不同用户项目不同,写死会误投)。

## 工作流(严格按序)

### 1. 确认输入文件
- 用户上传文件:`ListUploadedFiles` 确认。
- 文件在共享盘:用沙箱 `ls /share/...` 浏览;**不要用 bohr API 去列 /share 目录**(会递归返回自身)。
- 一条流水线至少需要主输入(.raw/.mzML/.msalign/.pbf 之一);TopPIC/MSPathFinderT 步还需 `.fasta`。
- 缺文件就 `AskUserInput`,**不要假设路径**。

### 2. 确认参数(HITL,必做)
提交前**必须**用 `AskUserInput` 让用户确认/编辑(完整字段见 `references/parameters.md`):
反卷积引擎(topfd/flashdeconv)、TopPIC 质量误差/PTM/FDR/decoy、机型(默认 `c16_m32_cpu`)。
- **用户取消 = 中止本次提交**,不得用默认值继续提交(取消是明确的停止信号,非"放行默认")。
- **一条链满足请求即止**:用户要"完整鉴定",跑一条 TopPIC 链即可;**追加第二条链(如 InformedProteomics)须先 `AskUserInput` 征得同意**,不得自动消费额外算力。

### 3. 写 pipeline.json(关键:决定跑哪条链/哪些步/从哪起)
按下方 schema 写一个 `pipeline.json`,放进工作目录。`steps` 是显式步骤列表,
**支持单工具、任意起点、两条主线**(见「pipeline.json 编写」)。

### 3.5 提交前本地校验(必做,零成本)
```bash
source /bohr-workspace/.bohr_env
python3 scripts/validate_pipeline.py --pipeline pipeline.json
# ok:true 才继续;否则按 errors[].{step,tool,field,fix} 改 pipeline.json 后重验
```
校验会列出**每处错误的位置(step/tool/field)+ 原因 + 允许值/修正建议**,据此修正后重验;避免提交无效配置而浪费作业。

### 4. 准备输入(两条通道,按大小/可写性选)

作业有两种方式获取输入文件:

| 通道 | 机制 | 适用 | 作业内可写 |
|---|---|---|---|
| **`-p` 上传目录** | `bohr job submit … -p ./`:该目录随作业上传,Bohrium 解压为**作业工作目录**(自动 `cd` 进入,命令用相对路径访问) | 小文件(< ~100MB):fasta、参数、小 mzML | ✅ 可写 |
| **dataset 挂载** | `make_dataset.py` 将文件注册为 Bohrium Dataset,作业经 `dataset_path` **只读**挂载到 `/bohr/<名>-<随机后缀>/v1/upload/` | 大谱图(GB 级 `.raw`/`.mzML`) | ❌ 只读 |

`submit_pipeline.py` 自动把 `inputs` 中的本地路径放入 `-p` 目录;`/bohr/…` 路径则作为 dataset 挂载引用,原样保留。

> **上传暂存目录(`td-job/`)由 submit 自建、上传成功后自动清理**——你**不要**手动建、手动删、或把它当残留清理。提交后工作区只剩:你写的 `pipeline.json` + `upload/`(原始输入)+ `td-result/<jobId>/`(结果),这是正常且干净的。

> **FASTA 必须走 `-p`,不可放 dataset。** TopPIC / MSPathFinderT 在搜索时会于 **FASTA 同目录**写入索引文件(`.fasta_idx`);dataset 为只读挂载,写索引将失败(`LOG ERROR: … fasta_idx could not be created`)。FASTA 体积通常为 KB–MB 级,放入 `-p` 即可;`make_dataset.py` 也会拒绝 FASTA 文件。

仅**谱图**需要建 dataset:
```bash
source /bohr-workspace/.bohr_env
python3 scripts/make_dataset.py --file <谱图路径.raw> --name <数据集名>   # 仅谱图;FASTA 勿用
# 返回真实挂载路径(含随机后缀与 upload 层);填入 pipeline.json 的 inputs.spectrum,
# 第 5 步 submit 时附带 --dataset-path /bohr/<名>-<后缀>/v1
```

### 5. 提交 job
```bash
source /bohr-workspace/.bohr_env
python3 scripts/submit_pipeline.py --pipeline pipeline.json [--dataset-path /bohr/<name>/v1]
# 返回 {jobId, status, pollAfterMs}
```
脚本将 **pipeline.json + 本地输入**置入 `-p` 上传目录,以配置的镜像提交;执行器位于镜像内,不随包上传。
现成样例见 `examples/`(完整链 / flashdeconv / 任意起点 / 单工具 / InformedProteomics)。

### 6. 轮询作业状态(**单次查询,不得循环阻塞**)
作业在 Bohrium 独立运行,完整链通常 6–15 分钟。**提交后查询一次即可,严禁在本轮内反复 `wait`+`poll` 直到完成**——长时间自旋会耗尽上下文、占用会话。
```bash
source /bohr-workspace/.bohr_env
python3 scripts/poll_job.py --job-id <JobId>   # 返回 status / done
```
- `done:true`(`completed`)→ 进入第 7 步 `collect_results.py`。
- 仍 `scheduling` / `running` → **向用户报告 jobId + 当前状态,然后结束本轮**;由用户稍后回来、或下一次调用时再查询一次。**不要自旋等待。**

作业与 sandbox 解耦:会话中断、sandbox 重建均不影响作业运行;jobId 记入 Memory,恢复后凭它继续轮询/回收。

### 7. 回收 + 汇报(bohr job download)
```bash
source /bohr-workspace/.bohr_env
python3 scripts/collect_results.py --job-id <JobId>
# bohr job download 拉回并扁平化到 /bohr-workspace/td-result/<JobId>/out/,解析 summary.json,
# 返回 status + metrics(PrSM/proteoform/protein 或 IcTda 数)+ 交付物本地路径 + 版本告警
```
- **每个 job 独占一目录** `td-result/<JobId>/`,内含:`out/`(**所有步骤产物** `00_msconvert/`、`01_topfd/`、`02_toppic/` …,含中间 mzML/msalign + `summary.json`,已扁平化、无冗余嵌套)+ **`<JobId>.zip`(完整结果包,保留供用户下载)**。返回的 `archive` 字段即该 zip 路径。
- 返回的 `version_warning` 非空时,应转告用户(镜像需更新)。

然后:`RecordArtifact` 标记 `summary.json` 与关键报告;Chat 只回摘要(PrSM/proteoform 数、FDR、链接),
不贴大表;`MemorySave` 记 `memories/projects/topdown/runs/<run>.md`(jobId/参数/结果位置)。

## pipeline.json 编写

```json
{
  "inputs": { "spectrum": "起点主输入(.raw/.mzML/.msalign/.pbf)",
              "fasta": "可选", "feature": "可选", "ms1ft": "可选" },
  "steps": [ { "tool": "工具名", "params": { } } ]
}
```
- `inputs.spectrum` = 这条链的**起点文件**(类型决定从哪起);`fasta` 等放外部输入。
- `steps` 按序列出工具;每步输入由执行器从上一步产物自动接线,你只管列工具+参数。

**典型组合:**

| 场景 | steps | inputs |
|---|---|---|
| 完整 TopPIC 链 | `msconvert → topfd → toppic` | spectrum=.raw, fasta |
| 用 FlashDeconv | `msconvert → flashdeconv → toppic` | spectrum=.raw, fasta(toppic 自动关 feature) |
| 从 mzML 起 | `topfd → toppic` | spectrum=.mzML, fasta |
| 从反卷积结果起 | `toppic` | spectrum=*_ms2.msalign, fasta, **feature(必需)** |
| 单工具(只转换) | `msconvert` | spectrum=.raw |
| InformedProteomics 链 | `pbfgen → promex → mspathfindert` | spectrum=.raw, fasta |

> 注:工具名只用 td 领域的:`msconvert/topfd/flashdeconv/toppic/pbfgen/promex/mspathfindert`。
> 不存在 `msconvert_only` 之类的字段;"只跑一步"就只在 steps 放一个工具。

**各起点的必需外部输入(缺了会 InputError):**
- `toppic` 步:必须有 `inputs.fasta` **和** `inputs.feature`(从 msalign 起步时两个都要给;
  完整链里 feature 由 topfd 自动产出,无需手填)。
- `mspathfindert` 步:必须有 `inputs.fasta`(+ 链内自动产的 pbf/ms1ft;从中途起步要补 `inputs.ms1ft`)。
- decoy/FDR:TopPIC 链 target-only 库 **必开** `toppic.decoy=true`;**InformedProteomics 链同理必开** `mspathfindert.tda=1`(做 target-decoy FDR)。

## 提示与排错

### 🚫 失败排查铁律(防臆断/幻觉)
1. **先定位真实原因,不得臆测**:运行 `collect_results.py`,读取返回的 `error` / `failed_log_tail` / `missing_inputs`——工具的真实报错即在其中。未读到真实报错前,不得编造原因。
2. **失败几乎都源于数据/配置,而非"管线不支持"**:常见真因为项目 ID 错误、dataset 路径漏 `upload/` 层、**FASTA 置于只读 dataset**(建索引失败)、缺 `feature`/`fasta`;应优先核查上述项。
3. **绝不下"X 不支持 / 架构限制"结论**:执行器**支持单工具、任意起点、以 `.msalign` 直接作为 toppic 输入、两条主线**(见「典型组合」表)。怀疑不支持时,应先查看真实报错并核对 `references/`,不得凭印象断言。
4. **绝不绕过执行器**手写 wrapper 直调工具二进制——违反铁律,且丢失自动接线、输入校验与 wine 封装,降低健壮性。

**判断要点:**
- **dataset 阈值(已硬拦)**:本地输入 > 100MB 时 `validate_pipeline.py` **直接报错并要求改走 make_dataset**(不能 -p);≤100MB 走 -p。阈值由校验器强制执行,判断与行动不会脱节。
- **decoy**:库是 target-only(无 DECOY_ 前缀序列)→ `toppic_params.decoy=true` / IP 链 `mspathfindert.tda=1`。不确定时启用 decoy(FDR 估计所必需)。
- **运行时长**:c16_m32 上一条完整链典型 6–15 分钟(toppic 的 unexpected-shift 搜索最慢);按 pollAfterMs 轮询即可,耗时属正常。

**submit_pipeline.py 成功返回示例:**
```json
{"ok": true, "jobId": "22907069", "status": "scheduling", "pollAfterMs": 20000, "nextTool": "poll_job.py"}
```

**常见错误:**
| 现象 | 原因 / 处理 |
|---|---|
| `AccessKey Invalid` | ① 确认 `ACCESS_KEY` 已 export(`echo ${ACCESS_KEY:0:6}` 非空);② 别用 `Authorization: Bearer`,REST 用 `accessKey:` 头;③ 短时间高频/并发同一 key 可能被限流,稍等重试;④ key 被重新生成会失效,让用户重取 |
| `ParamError ... validation failed` | pipeline.json 写了不存在的字段;只用 `references/parameters.md` 列的键,不要臆造(如 `msconvert_only`) |
| `no files found matching X` | 输入路径问题——脚本已把本地输入绝对化;确认文件真存在、或 dataset 路径对 |
| job `status=-1`(失败) | `collect_results.py` 直接返回 `failed_step` + `error` + **`failed_log_tail`(工具真实报错)** + `missing_inputs`;依据真实报错修正,勿自行臆测 |
| 缺输入(missing_inputs) | 某步要的外部输入没给(如 toppic 缺 fasta、mspathfindert 缺 fasta)→ 补 `inputs.fasta` |
| `ParamError`(IP 链 tda) | `tda` 是**整数 0/1 不是 bool**;target-only 库写 `"tda": 1`(不是 `true`) |
| `Dataset ... has been deleted` | 根因=Bohrium 给名字加随机后缀(`/bohr/<name>-xxxx/v1`),别假设 `/bohr/<name>/v1`;**make_dataset.py 已自动从 API 返回真实路径**,用它给的 `spectrum_mount`/`--dataset-path` 即可。create 后 `bohr dataset list` 或 `GET /openapi/v1/ds/?projectId=` 也能查真实 path |
| dataset 上传 panic(Client.Timeout) | bohr CLI 上传大文件超时会 panic;Shrimp 内网通常正常,慢速网络下重试(支持断点续传)或改走 -p |
| `bohr job download` 对 failed job panic | 失败 job 没 out.zip;改用 OpenAPI `GET /openapi/v1/job/<id>` 取 STDOUTERR 看错误(或本 skill 已把失败步日志收进 out/failed_logs/) |
| IP 链看结果 | InformedProteomics 产 `*_IcTda.tsv`(非 prsm);collect_results 的 `ictda_ids` 即鉴定数,QValue≤0.01 为 1% FDR |

## HARD STOP(成本确认)
机型为大核数(如 `c32_*`)或预计长时运行,提交前**必须** `AskUserInput` 用 checkbox 让用户确认费用。不静默提交高成本 job。

## 边界
- 不在 sandbox 里跑 msconvert/TopFD/TopPIC 等(它们在 Bohrium 镜像里,经作业跑)。
- GB 级谱图不经 `-p` 上传(经 dataset 挂载),也不读入对话上下文。
- 不臆造文件路径或参数;不确定就 `AskUserInput`。
- **禁止 `cat` 执行器日志 / 大 TSV**(toppic 进度日志可达数百万字符):指标取 `collect_results.py` 的 `metrics`;需细节时 `head -40` 读 TSV 顶部统计块即可。
- 不在 Bohrium 镜像库查找单工具镜像;一律使用配置的 `IMAGE_ADDRESS`(默认取自 `image.txt`)。
- ACCESS_KEY 由平台注入,不写进 prompt/日志/文件。

## 配置(由平台注入)
本 skill 需要的配置在上方 frontmatter 的 `configFields` / `metadata.openclaw` 中声明,由平台(OpenClaw)以**环境变量**注入;sandbox 内经 `setup.sh` 落到 `/bohr-workspace/.bohr_env`,后续命令 `source` 即用:
- `ACCESS_KEY`(`primaryEnv`,**必填**;平台亦可能注入 `BOHR_ACCESS_KEY`,脚本两者都认)
- `PROJECT_ID`(**必填**,无默认——缺失时不得硬编码,向用户索取)
- `IMAGE_ADDRESS`(可选,默认取 skill 的 `image.txt`,仅临时换版本时填)、`MACHINE_TYPE`(可选,默认 `c16_m32_cpu`)

> 具体在何处填这些值,以平台的 skill 配置界面/文档为准(本 skill 不假设具体配置文件名)。
