# 待平台确认的问题(OpenClaw / Shrimp)

下列是开发 skill 时**做了假设、但平台才权威**的点。向平台 agent / 文档确认后,把答案填到「答案」处,再据此修订 skill(尤其 `scripts/setup.sh` 的 key 兜底、`SKILL.md` 配置段、是否自装 bohr)。

---

## 🔴 凭据 / 配置注入(最关键,本项目踩坑最多)

### 1. 凭据注入的变量名
平台把 Access Key 注入成 `ACCESS_KEY` 还是 `BOHR_ACCESS_KEY`?
- 现状:实测两种都出现过,脚本现在 `${ACCESS_KEY:-${BOHR_ACCESS_KEY:-}}` 两个都认。
- **答案:**

### 2. 凭据注入的时机与持久性
是**每次 Bash 调用**都注入,还是只在授权后/特定回合?env 在多次 Bash 调用之间持久吗?
- 假设:每次 Bash 是独立 shell、env 不持久 → 靠 `/bohr-workspace/.bohr_env` + 每条命令开头 `source`。
- **答案:**

### 3. PROJECT_ID 怎么注入
平台有无内置 PROJECT_ID 注入?还是必须靠 skill `configFields` 声明、用户填值?
- 现状:实测未被自动注入,曾导致 agent 硬编码(已禁止);缺失时改向用户索取。
- **答案:**

### 4. configFields → 环境变量的映射
frontmatter 里 `configFields`(IMAGE_ADDRESS / PROJECT_ID / MACHINE_TYPE)用户填的值,会**自动成为 sandbox 环境变量**(脚本 `os.environ` 可读)吗?还是只有 `metadata.openclaw.primaryEnv`(ACCESS_KEY)会?
- **答案:**

### 5. 配置在哪里填
用户实际在**哪个界面/文件**设 ACCESS_KEY / PROJECT_ID?有没有 `openclaw.json` 这类文件,还是配置界面?
- 现状:SKILL 配置段已删除臆造的文件名,改为"由平台注入,以平台界面/文档为准"。
- **答案:**

---

## 🟡 frontmatter / 部署

### 6. frontmatter 字段是否符合 OpenClaw schema
`type: sandbox`、`requires: [bohrium-job]`、`configFields`、`metadata.openclaw.primaryEnv`、`l0/l1` 是标准 key 吗?声明 API key 用 `primaryEnv` 对吗?
- **答案:**

### 7. skill 安装路径 + 从 git URL 部署
装到 `/data/skills/topdown-proteomics/` 对吗?平台支持**直接指向 git 仓库**安装 skill 吗,还是需手动 clone?
- 仓库:https://github.com/Cheng77c/topdown-proteomics-skill
- **答案:**

### 8. `requires: bohrium-job` 的含义
它是否意味着 bohrium-job skill 必须先装、并由它提供 `bohr` CLI + 鉴权?那 `setup.sh` 还需不需要自己装 bohr?
- 现状:setup.sh 自己装 bohr CLI(幂等)。若平台已提供则可删。
- **答案:**

---

## 🟢 行为机制

### 9. 参数表单字段如何决定
HITL 参数表单显示哪些字段,是由 `AskUserInput` 调用决定,还是 configFields?能否控制?
- 现象:曾出现"表单只显示几个参数"的疑问。
- **答案:**

### 10. 作业轮询有无原生异步
平台支持**作业完成时自动回调 / 再唤醒 agent** 吗?还是只能"查一次就停,用户下次回来再查"?
- 现状:skill 按后者设计(单次轮询、不自旋)。
- **答案:**

---

> 优先确认 1–5(凭据/配置注入)——本项目最多坑、最影响稳定性。
