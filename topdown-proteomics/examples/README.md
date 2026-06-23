# pipeline.json 示例

每个文件对应一个场景(`_scenario` 字段仅说明,执行器忽略下划线开头的键)。
用法:照着改 `inputs`(起点文件 + fasta/feature 等)和 `steps`,然后
`python3 ../scripts/submit_pipeline.py --pipeline <file>.json`。

| 文件 | 场景 |
|---|---|
| `full-toppic-chain.json` | 完整 TopPIC 链(msconvert→topfd→toppic) |
| `flashdeconv-chain.json` | 用 FlashDeconv 替代 topfd |
| `toppic-from-msalign.json` | 任意起点:从反卷积结果只跑 toppic |
| `single-msconvert.json` | 单工具:只做格式转换 |
| `informedproteomics-chain.json` | 主线 B:InformedProteomics 链 |

参数键见 `../references/parameters.md`。
