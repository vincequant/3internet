# P51 練兵崩潰修復（2026-10-19）

## 一句話

旁聽客戶端「一進遊戲點練兵就崩」的根因是**共用查表工具的回退語義錯誤**（把容器當元素回傳），
加上**面板元素容器在旁聽客戶端是空的**；兩個修法都已實機驗證，練兵崩潰消失。

## 崩潰鏈（全部為實測，非推論）

| # | EIP | 現場 | 判讀 |
|---|---|---|---|
| 1 | `0x417C29` `mov eax,[eax+0x1c]` | eax=this=`0xFFFFFB4E`，返回址 `0x4A3F57` | 錯誤型別物件被當 CWnd/元素使用 |
| 2 | `0x49B0E3` / `0x4B0822` | this=`0xFFFFF95A` / `0xFFFFFA5A` | 同一族「小負數符號擴展」假指標 |
| 3 | `0x66E8006A` / `0x6A000127` | 從 `call [eax+0x9c]` 跳進資料（eax=`0x50DCF4`＝函數指標表） | 容器被當元素做虛呼叫 |
| 4 | `0x4A3E1E` `mov esi,[ebx+0x3c]` | ebx=0（查表回 NULL），edi=`0x49D3230`（對話框有效） | 面板元素容器**沒有元素** |
| 5 | `0x4195B1` `mov esi,[eax+4]` | eax=0x12E（id 被當容器） | **我的補丁 bug**：用 `jmp` 取代 `call` 卻 pop 返回地址，參數錯位 |

## 兩個補丁

### 1) `patch_element_fallback.py` — 查表落空改回「真實元素」

- 站點：`0x4195AF` 還原 `33 FF`（`xor edi,edi`，NULL 種子）；`0x4195C4` 的 `call 0x4D3214`（動態轉型）改道 cave `0x200000`。
- 行為：落空時回傳「同容器裡第一個通過同一轉型的真實元素」→ 欄位偏移與 vtable 都是合法型別，不再把容器當元素。
- cave：`call 0x4D3214` / `test eax,eax` / `jz` / `test edi,edi` / `jnz` / `mov edi,eax` / `jmp 0x4195C9`（22 bytes）。

### 2) `patch_panel_row_fallback.py` — 容器為空時補一個真實元素

- 站點（三個活著的查表呼叫點）：`0x4A3E15`（id 0x12E）、`0x48F06C`（0x12C）、`0x48F215`（0x12C）。
- 行為：查表回 NULL 時，用遊戲自己的 `operator new(0x44)`（`0x4D1D22`）+ 建構子 `0x485256` 造一個同型別物件（vtable `0x50A4F8`；基類 ctor `0x484101` 會設 `+0x38=-1、+0x3C=0、+0x40=0`），快取在 cave 內重用。
- cave（每站一份，共 47 bytes）：`call 0x4195A9` → NULL 則取/建 dummy → `jmp 站點+5`。

### 關鍵教訓（`jmp` 取代 `call` 的堆疊語義）

`call X` 會壓返回地址、`jmp cave` 不會。cave 內要呼叫原目標時**直接 `call 目標`**（此時棧頂正好是原本壓好的參數），
結束用 `jmp 站點+5` 回去；**不要 pop/push 返回地址**，否則參數整體錯位（本次 `0x4195B1` 崩潰就是這樣產生的）。

## 實機驗收

- 19:33:17 一鍵內測武裝：21 站 nullguard + 2 站 suppress + 三台開局守衛 18 站 + 兩個回退 cave（風夜 pid 592）。
- `verify_shadow_caves.py` 對運行中進程逐位元組核對（`verify-caves-live.json`）：
  - `0x4195AF = 33 FF`（NULL 語義）✔
  - element cave `0x200000`：`calls_cast ✔`、`jumps_back ✔`
  - panel caves `0x210000/40/80`：`calls_walker ✔`、`jumps_back ✔` → **ok: true**
- 用戶實測：**練兵崩潰消失**。

## 未決：練兵之後客戶端「掛掉」

- 19:35:0x 崩潰台帳新增 5 筆，EIP `0x7BFA4376`（不在映像內），呼叫鏈
  `0x4A3EC6 → 0x4F598D → 0x485477 → 0x485431 → 0x50DCF4 → 0x485570 → 0x4D2019 → 0x7BFA4376`，
  `eax=edi=0x55776F42`、`ebx=0x44C9EB0`。
- 同時間 `status.json`：`present=true, connected=true, in_map=true, mode=3, phase=0, tx=30, rx_backlog=6`，
  最後收包距 20.5s → **進程還在，但世界沒推進**。
- 待查：是否為 dummy 元素進入 `0x4842D4` 的通知路徑（vtable `0x50A4F8` 上的方法）碰到「真實元素才有的欄位」；
  或練兵數值溢滿（`+0x3C` 是數量欄）導致後續計算跳飛。
- 下一步：對 `0x7BFA4376` 做映射（Wine 模組基址）＋靜態反組譯 `0x4D2019 / 0x485570 / 0x485431 / 0x485477`，
  確認是哪一個虛呼叫跳飛；再決定「dummy 是否要跳過通知」或「練兵數值夾緊」。

## 檔案

- 工具（本地 `~/sgi-fengye-lab/shadow/tools/` 與 repo `research/client/protocol-lab/` 同份）：
  `patch_element_fallback.py`、`patch_panel_row_fallback.py`、`verify_shadow_caves.py`、`p51_shadow_inject.py`（移除 0x195AF 站點）、`one_click_test.sh`（新增 6d 步）。
- 證據：本目錄（崩潰台帳原始檔＋解碼 JSON、三輪一鍵內測日誌、cave 驗證 JSON）。
