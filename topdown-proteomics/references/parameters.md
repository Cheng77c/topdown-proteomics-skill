# Top-down 参数完整参考(镜像实际版本)

> 来源:镜像内各工具 `--help` 实测 + 镜像内置参数校验。
> 版本:**msconvert ProteoWizard 3.0.26058 · TopFD 1.8.1 · TopPIC 1.8.1 · FLASHDeconv 3.5.0 · InformedProteomics**。
> 以本文件为准——网上较老版本(如 TopFD/TopPIC 1.5.3)的默认值/枚举与本镜像不一致。

`pipeline.json` 的 `steps[].params` 用下表 **snake_case 键**(括号是 CLI flag)。留空=工具默认。

```json
{ "inputs": { "spectrum": "...", "fasta": "...", "feature": "...", "ms1ft": "..." },
  "steps": [ { "tool": "...", "params": { } } ] }
```

---

## ⚠️ 会导致 ParamError 的校验约束(最易踩,先看)

**toppic:**
- `mass_error_tolerance` **只接受 5 / 10 / 15**(整数 ppm),其它值报错。默认 10。
- `activation` ∈ `FILE|CID|ETD|HCD|UVPD`(1.8.1 **无 MPD**)。
- `num_shift` ∈ `0|1|2`。
- `spectrum_cutoff_type` / `proteoform_cutoff_type` ∈ `EVALUE|FDR`。**用 FDR 必须同时 `decoy=true`**。
- `fixed_mod` ∈ `C57|C58|可读文件`;`n_terminal_form` 每项 ∈ `NONE|NME|NME_ACETYLATION|M_ACETYLATION`。
- **`no_topfd_feature=true` 且 `num_shift>=1` → 已知崩溃,代码直接拦截报错**(flashdeconv 链自动设 no_topfd_feature,故此时别再设 num_shift>=1)。

**mspathfindert(IP 链):** `tda` 是**整数**(0/1,target-decoy 模式),不是 bool;target-only 库设 `1`。

---

## 主线 A:TopPIC 链 `msconvert → topfd | flashdeconv → toppic`

### msconvert 3.0.26058(.raw→.mzML)谱图转换
> **`filters` 默认 = `["peakPicking true 1-"]`** —— 执行器默认就做质心化(top-down 必需),不设即生效;要改/关质心化才显式写 `filters`。常规转换整个 `params` 留空即可。

**结构化参数键**(放进 `params{}`,均已映射,无需 extra_args):

| 键 (flag) | 类型 | 默认 | 说明 |
|---|---|---|---|
| `output_format` | --mzML/--mzXML/--mz5/--mzMLb/--mgf/--text/--ms1/--cms1/--ms2/--cms2 | mzML | 输出格式 |
| `filters` | --filter(字符串数组,可多条,按序执行) | ["peakPicking true 1-"] | spectrum filter,见下表 |
| `chromatogram_filters` | --chromatogramFilter(数组) | — | 色谱图 filter(index / lockmassRefiner) |
| `extension` | -e | — | 输出扩展名(自动去前导 `.`) |
| `outfile` | --outfile | — | 覆盖输出文件名(多输入时禁用) |
| `precision` | --64 / --32 | 64 | 默认二进制编码位数 |
| `mz_precision` | --mz64 / --mz32 | 64 | m/z 精度 |
| `inten_precision` | --inten64 / --inten32 | 32 | 强度精度 |
| `zlib` | -z | true | zlib 压缩 |
| `gzip` | -g | false | 整文件再 gzip(加 .gz) |
| `numpress_linear` | --numpressLinear | false | numpress 线性压缩(m/z+RT) |
| `numpress_slof` | --numpressSlof | false | numpress short-logged-float(强度) |
| `numpress_pic` | --numpressPic | false | numpress 正整数(强度) |
| `numpress_all` | --numpressAll | false | = linear + slof |
| `numpress_linear_abs_tol` | --numpressLinearAbsTol | -1 | 线性 numpress 绝对容差(须 ≥ -1) |
| `mz_truncation` / `inten_truncation` | --mzTruncation / --intenTruncation | 0 | 截断尾数位(须 ≥ -1) |
| `mz_delta` / `inten_delta` | --mzDelta / --intenDelta | false | delta 预测 |
| `mz_linear` / `inten_linear` | --mzLinear / --intenLinear | false | linear 预测 |
| `mzmlb_chunk_size` / `mzmlb_compression_level` | --mzMLbChunkSize / --mzMLbCompressionLevel | 1048576 / 4(0–9) | mzMLb 专用 |
| `verbose` | -v | true | 详细进度 |
| `noindex` | --noindex | false | 不写索引 |
| `merge` | --merge | false | 多输入合并为单文件 |
| `run_index_set` | --runIndexSet | — | 多 run 源只选指定 run |
| `single_threaded` | --singleThreaded | false | 单线程读写 |
| `continue_on_error` | --continueOnError | false | 出错跳过继续 |
| `filelist` (-f) / `config_file` (-c) / `contact_info` (-i) | 文件 | — | 文件列表 / 配置 / 联系人 |

其余 vendor 相关布尔(默认 false,需要才设):`sim_as_spectra` `srm_as_spectra` `combine_ion_mobility_spectra` `dda_processing` `ignore_calibration_scans` `accept_zero_length_spectra` `ignore_missing_zero_samples` `ignore_unknown_instrument_error` `strip_location_from_source_files` `strip_version_from_software`。

**`filters` 数组里可用的 spectrum filter**(整条字符串传入;`int_set` 语法如 `1-`/`[0,3]`/`9`):

| filter(语法) | 作用 |
|---|---|
| `peakPicking [<cwt\|vendor> [snr=] [peakSpace=] [msLevel=]]` | 质心化;**vendor 模式必须排第一**。默认 `peakPicking true 1-` |
| `msLevel <mslevels>` | 按 MS level 过滤(如 `2-` 只留 MS2) |
| `index <int_set>` / `id <id_set>` / `scanNumber <set>` / `scanEvent <set>` | 按 index / native id / scan 号 / scan event 选谱 |
| `scanTime <range>` | 按保留时间(秒)区间过滤 |
| `chargeState <set>` | 按电荷过滤(`0`=含无电荷信息谱) |
| `precursorRecalculation` / `precursorRefine` | 用前一张 MS1 重算 MS2 前体 m/z/电荷(orbitrap/FT[/TOF]) |
| `mzRefiner <id files> [thresholdScore=][thresholdValue=]…` | 用鉴定结果校正 m/z(orbitrap/FT/TOF) |
| `lockmassRefiner mz= mzNegIons= tol=` | Waters lockmass 校正 |
| `threshold <type> <value> <orientation> [mslevels]` | 按强度/计数裁峰(type: count/absolute/bpi-relative/tic-relative/tic-cutoff;orientation: most-intense/least-intense) |
| `mzWindow <mzrange>` | 只留 m/z 窗口内峰 |
| `mzPrecursors <list> [mzTol=] [target=][mode=]` / `isolationWindows` / `isolationWidth` | 按前体 m/z / 隔离窗 / 隔离宽筛谱 |
| `defaultArrayLength <range>` | 按峰数过滤谱 |
| `zeroSamples <removeExtra\|addMissing[=n]> [mslevels]` | 去冗余零 / 补零 |
| `mzPresent <mz_list> [mzTol=][type=][threshold=][orientation=][mode=]` | 按目标峰是否存在保留/排除谱 |
| `MS2Denoise [peaks_in_window [width_Da [relax]]]` / `MS2Deisotope [hi_res] [Poisson]` | MS2 去噪 / 去同位素 |
| `ETDFilter [...]` | 去 ETD 未反应前体/charge-reduced/中性丢失 |
| `chargeStatePredictor [...]` / `turbocharger [...]` | 预测 MSn 前体电荷 |
| `activation <type> [mode=]` | 按活化类型过滤(ETD/CID/HCD/UVPD…) |
| `collisionEnergy low= high= [mode=]` | 按碰撞能过滤 |
| `analyzer <quad\|orbi\|FT\|IT\|TOF>` / `polarity <positive\|negative>` | 按分析器 / 极性过滤 |
| `scanSumming [...]` / `demultiplex [...]` / `diaUmpire params=` | 子扫描求和 / DIA 解复用 / DIA-Umpire |
| `metadataFixer` / `titleMaker <fmt>` / `sortByScanTime` / `stripIT` / `mzShift` / `thermoScanFilter` | 修 TIC-BPI / 生成标题 / 排序 / 去离子阱 MS1 / 平移 m/z / Thermo scan 文本过滤 |

### topfd 1.8.1(.mzML→*_ms2.msalign + *_ms2.feature)反卷积
| 键 (flag) | 类型/范围 | 默认 | 说明 |
|---|---|---|---|
| `activation` (-a) | FILE\|CID\|ETD\|HCD\|MPD\|UVPD | FILE | 碎裂方式 |
| `max_charge` (-c) | 正整数 | 30 | 最大电荷 |
| `max_mass` (-m) | 正数 Da | **50000** | 最大单同位素质量 |
| `mz_error` (-e) | 正数 | 0.02 | m/z 误差 |
| `ms_one_sn_ratio` (-r) | 正数 | 3 | MS1 信噪比 |
| `ms_two_sn_ratio` (-s) | 正数 | 1 | MS2 信噪比 |
| `precursor_window` (-w) | 正数 | 3.0 | 前体窗口(文件自带则忽略) |
| `missing_level_one` (-o) | bool | false | 输入无 MS1 |
| `use_msdeconv` (-n) | bool | false | 用 MS-Deconv 打分(默认 EnvCNN) |
| `env_cnn_cutoff` (-v) | [0,1] | 0 | EnvCNN 分数 cutoff |
| `ecscore_cutoff` (-t) | [0,1] | 0.1 | ECScore cutoff |
| `min_scan_number` (-b) | 1\|2\|3 | 1 | feature 最少跨几个 MS1 scan |
| `disable_frag_num_filtering` (-d) | bool | false | 关碎片数过滤 |
| `single_scan_noise` (-i) | bool | false | 单扫描噪声过滤 |
| `disable_additional_feature_search` (-f) | bool | false | 关额外 feature 搜索 |
| `thread_number` (-u) | 正整数 | 1 | 线程数(机型够则不设) |
| `skip_html_folder` (-g) | bool | false | 跳过 HTML(省时) |

### flashdeconv 3.5.0(.mzML→msalign+feature)反卷积(替代 topfd)
`min_mz`、`max_mz`、`min_rt`、`max_rt`、`max_ms_level`(其余用默认)。
> 执行器在 flashdeconv 链下自动给 toppic 注入 `no_topfd_feature=true`(feature 列布局与 TopFD 不同)。

### toppic 1.8.1(msalign + fasta [+ feature]→PrSM/proteoform)搜索
| 键 (flag) | 类型/枚举 | 默认 | 说明 |
|---|---|---|---|
| `decoy` (-d) | bool | false | shuffled decoy 估 FDR(target-only 库**必开**) |
| `mass_error_tolerance` (-e) | **5\|10\|15** | 10 | 质量误差 ppm(只接受这三值) |
| `activation` (-a) | FILE\|CID\|ETD\|HCD\|UVPD | FILE | 碎裂方式(无 MPD) |
| `fixed_mod` (-f) | C57\|C58\|文件 | 无 | 固定修饰 |
| `n_terminal_form` (-n) | NONE,NME,NME_ACETYLATION,M_ACETYLATION | 同左全集 | N 端形式 |
| `proteoform_type` (-R) | 列表 | — | 允许的 proteoform 类型(1.8.1 新) |
| `num_shift` (-s) | 0\|1\|2 | 1 | 最大未知质量偏移数 |
| `min_shift` (-m) | Da | -500 | 偏移下限 |
| `max_shift` (-M) | Da | 500 | 偏移上限 |
| `variable_ptm_num` (-S) | 正整数 | 3 | 最大可变 PTM 数(1.8.1 新) |
| `variable_ptm_file_name` (-b) | 文件 | 无 | 可变修饰文件 |
| `proteoform_error_tolerance` (-p) | 正数 Da | 1.2 | PrSM cluster 误差 |
| `spectrum_cutoff_type` (-t) | EVALUE\|FDR | EVALUE | 谱图级 cutoff 类型 |
| `spectrum_cutoff_value` (-v) | 正数 | 0.01 | 谱图级 cutoff 值 |
| `proteoform_cutoff_type` (-T) | EVALUE\|FDR | EVALUE | proteoform 级 cutoff 类型 |
| `proteoform_cutoff_value` (-V) | 正数 | 0.01 | proteoform 级 cutoff 值(1% FDR 即此设 0.01 + FDR) |
| `num_combined_spectra` (-r) | 正整数 | 1 | 合并谱图数(交替碎裂用 2/3) |
| `mod_file_name` (-B) | 文件 | 无 | local/common PTM 文件 |
| `miscore_threshold` (-H) | [0,1] | 0.15 | 修饰识别分阈值 |
| `no_topfd_feature` (-x) | bool | false | 不用 feature(见上方崩溃约束) |
| `keep_decoy_ids` (-K) | bool | false | 保留 decoy 鉴定 |
| `keep_temp_files` (-k) | bool | false | 保留中间文件 |
| `thread_number` (-u) | 正整数 | 1 | 线程数 |
| `skip_html_folder` (-g) | bool | false | 跳过 HTML |

---

## 主线 B:InformedProteomics 链 `pbfgen → promex → mspathfindert`

### pbfgen(.raw/.mzML→.pbf)
通常留空。可选:`start`/`end`(限定 scan 范围)。

### promex(.pbf→.ms1ft)特征检测
| 键 (flag) | 范围 | 默认 | 说明 |
|---|---|---|---|
| `min_charge` (-MinCharge) | 1–60 | 1 | 最小电荷 |
| `max_charge` (-MaxCharge) | 1–60 | 60 | 最大电荷 |
| `min_mass` (-MinMass) | 600–100000 | 2000 | 最小质量 Da |
| `max_mass` (-MaxMass) | 600–100000 | 50000 | 最大质量 Da |
| `bin_res_ppm` (-BinResPPM) | 1\|2\|4\|8\|16 | — | 分箱分辨率 ppm |
| `score_threshold` (-ScoreThreshold) | 数 | -10 | 似然分阈值 |
| `max_threads` (-MaxThreads) | 整数 | 0(自动) | 线程数 |

### mspathfindert(.pbf + .ms1ft + fasta→*_IcTda.tsv)搜索
| 键 (flag) | 类型/范围 | 默认 | 说明 |
|---|---|---|---|
| `tda` (-tda) | **整数 0/1** | — | target-decoy 搜索模式(做 FDR 设 1) |
| `ic_mode` (-ic) | 整数 | 1(SingleInternalCleavage) | 搜索模式 |
| `pm_tolerance` (-PMTolerance) | ppm | 10 | 前体容差 |
| `frag_tolerance` (-FragTolerance) | ppm | 10 | 碎片容差 |
| `min_length` / `max_length` | 整数 | 21 / 500 | 序列长度 |
| `min_charge` / `max_charge` | 整数 | 2 / 50 | 前体电荷 |
| `min_frag_charge` / `max_frag_charge` | 整数 | 1 / 20 | 碎片电荷 |
| `min_mass` / `max_mass` | Da | 3000 / 50000 | 质量范围 |
| `num_matches` (-NumMatchesPerSpec) | 整数 | 1 | 每谱报告数 |
| `include_decoys` (-IncludeDecoys) | bool | false | 结果含 decoy |
| `tag_search` (-TagSearch) | bool | — | 标签搜索 |
| `mod_file` (-ModificationFile) | 文件 | 无 | 静/动修饰文件 |
| `activation` (-ActivationMethod) | 枚举 | Unknown(6) | 活化方式 |
| `threads` (-ThreadCount) | 整数 | 0(自动) | 线程数 |
| `overwrite` (-overwrite) | bool | false | 覆盖已有结果 |

---

## 产物
- TopPIC:`*_toppic_prsm*.tsv`、`*_toppic_proteoform*.tsv`(PrSM 数=数据行,扣参数块表头)
- InformedProteomics:`*_IcTda.tsv`(target-decoy)、`*_IcTarget.tsv`、`*_IcDecoy.tsv`;QValue≤0.01 即 1% FDR
- 中间文件(mzML/msalign/feature/pbf/ms1ft)留计算节点 work/,不回收
