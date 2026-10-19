# 備份點（GitHub: vincequant/3internet）

這個 repo 只存放**可公開、可重建**的研究資產；遊戲本體、存檔、帳號憑據、大型二進位一律不進版控。
目的是「下一次崩潰後能回到上一個儲存點」，不是完整鏡像。

## 這裡有什麼

| 路徑 | 內容 |
|---|---|
| `research/client/protocol-lab/` | 旁聽（風夜）實驗室整包工具：一鍵內測、開局守衛、元素查表回退、面板行補位、cave 驗證、診斷探針（視窗/執行緒/全域/回合狀態） |
| `research/protocol-archive/evidence/` | 每次實驗的證據包（崩潰台帳、解碼 JSON、日誌、NOTES） |
| `research/protocol-archive/disasm/` | SANPK / Koeinm 反編譯錨點與類別佈局（本 repo 內既有） |
| `research/ai/`, `research/reports/` | 分析與交接文件 |

### 最近兩個儲存點

- `abecb22` **P51 練兵崩潰修復**：查表回退（`0x4195C4` → cave，落空回傳同容器第一個通過轉型的真實元素）＋面板行補位（`0x4A3E15 / 0x48F06C / 0x48F215`，落空時用遊戲自己的 ctor 造同型別元素）。
- `70392bb` **停擺判定**：`0x53BA54` 重入鎖卡 1、`queue_84b4` 只增、`phase_4d8` 不動、年停在 200（其他兩台 201）→ 世界停格、客戶端本身沒死。

## 崩潰後怎麼恢復

1. 拉回來：
   ```
   git clone https://github.com/vincequant/3internet.git
   ```
   （或在本機既有工作區 `git fetch origin && git log origin/main`）
2. 工具要放回實驗室目錄才跑得動：
   ```
   cp -R research/client/protocol-lab/*.py  ~/sgi-fengye-lab/shadow/tools/
   cp -R research/client/protocol-lab/*.sh  ~/sgi-fengye-lab/shadow/
   ```
   （`patch_start_nulls.py`、`p51_shadow_inject.py`、`one_click_test.sh` 等以 repo 版本為準）
3. 一鍵武裝：
   ```
   bash ~/sgi-fengye-lab/shadow/one_click_test.sh
   ```
   它會做：三開 → 建房/進房 → 21 站護欄 → 2 站抑制 → 三台 18 站開局守衛 →
   元素查表回退 → 面板行補位 → D8 藏身 → slot → 情報台會話。
4. 驗證 cave 在位（換成實際 wine pid）：
   ```
   .../verify_shadow_caves.py <wine_pid>     # 應回 ok: true
   ```

## 不在 repo 裡的東西（要自己留）

- 遊戲本體（`SANPK.exe` 等）與存檔。
- `~/sgi-fengye-lab/shadow/fengye-credentials.json`、`query-credentials*.json` 等帳號憑據。
- `protocol-lab/python32/`（Wine 用的 Python 執行時）與字型。
- 大型 pcap、影片。

## 本機 `.git` 衛生

`.git` 內有早前 `git add -A` 留下的未引用物件（數 GB）。它們不影響 push（只推可達物件），
若日後要縮小本機 repo，可執行（會清掉 Codex checkpoint ref 未引用的物件）：
```
git reflog expire --expire=now --all && git gc --prune=now
```
