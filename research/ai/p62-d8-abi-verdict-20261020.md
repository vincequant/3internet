# P62 D8 ABI 判定撤回與狀態對照（2026-10-20 07:4x）

**一句話**：P61 的「ABI 猜錯（4c80 三參、4b60 兩參）」是誤判。現行 DLL 位元組級核對顯示
`0x4c80` 是 **1 參 cdecl**、`0x4b60` 是 **4 參 cdecl**，與 P34/P51 一致；照 0x10002502
的「形狀」重寫會把 body/len 讀成垃圾。P61 的負結果要用「發射時幽靈已藏身、局已開」來解釋，
不是通道壞。

---

## 1. 位元組證據（現行影子 Koeinm.dll）

- 檔：`~/Library/Application Support/SGI-Wine/prefix-fengye-shadow/drive_c/sgi/run-3.5/3I/Koeinm.dll`
- SHA-256：`629f500a4fbb1fdcb056c4d681476a31f0ae31e6cd9d26221e8faaeb41283841`
- PE：`.text` RVA `0x1000`、raw `0x400` ⇒ `file_off = 0x400 + (rva - 0x1000)`

### 1.1 `0x10004b60`（可靠提交）

```
10004b60  8b 44 24 04        mov  eax,[esp+4]        ; arg1 = netobj
10004b64  8b 88 48 01 00 00  mov  ecx,[eax+0x148]    ; is_host
10004b6a  85 c9              test ecx,ecx
10004b6c  74 19              je   10004b87          ; 非主機 -> 另一分支
10004b6e  8b 4c 24 10        mov  ecx,[esp+0x10]     ; arg4 = len
10004b72  8b 54 24 0c        mov  edx,[esp+0xc]      ; arg3 = buf
10004b76  51                 push ecx                ; len
10004b77  8b 4c 24 0c        mov  ecx,[esp+0xc]      ; 移位後 = arg2 = target
10004b7b  52                 push edx                ; buf
10004b7c  51                 push ecx                ; target
10004b7d  50                 push eax                ; netobj
10004b7e  e8 5d 19 00 00     call 100064e0
10004b83  83 c4 10           add  esp,0x10
10004b86  c3                 ret
```

⇒ **`4b60(netobj, target, buf, len)`，4 參 cdecl，裸 `ret`。** 另一分支 `0x10004b87`
同樣取 `[esp+c]/[esp+10]` 兩格後四參呼叫 `10006340`。

### 1.2 `0x10004c80`（GetHostOrSelfID）

```
10004c80  8b 44 24 04        mov  eax,[esp+4]        ; 只讀 arg1 = netobj
10004c84  8b 88 48 01 00 00  mov  ecx,[eax+0x148]
10004c8a  85 c9              test ecx,ecx
10004c8c  74 09              je   10004c97
10004c8e  8b 80 b8 43 00 00  mov  eax,[eax+0x43b8]    ; 主機：row0
10004c94  8b 00              mov  eax,[eax]
10004c96  c3                 ret                     ;   回 row0.id
10004c97  83 b8 bc 43 00 00 01  cmp dword [eax+0x43bc],1   ; 成員：rowcount
10004c9e  7e 0d              jle  10004cad
10004ca0  8b 88 b8 43 00 00  mov  ecx,[eax+0x43b8]
10004ca6  8b 81 64 01 00 00  mov  eax,[ecx+0x164]    ;   回 row1.id
10004cac  c3                 ret
10004cad  33 c0              xor  eax,eax             ; rowcount<=1 回 0
10004caf  c3                 ret
```

⇒ **`4c80(netobj)`，1 參 cdecl；回傳 0 代表「沒有可用的目標」。**

## 2. 為什麼 `0x10002502` 看起來像「3 參 / 2 參」

```
10002502  8d 44 24 04     lea  eax,[esp+4]     ; &local（本函式的 len/緩衝槽）
10002506  6a 04           push 4               ; ┐ 這兩格是「先替後面的 4b60 預留」
10002508  50              push eax             ; ┘
10002509  56              push esi             ; netobj
1000250a  e8 71 27 00 00  call 10004c80        ; 4c80 只看第一格，另兩格留在棧上
1000250f  83 c4 04        add  esp,4           ; 丢掉一格
10002512  50              push eax             ; target
10002513  56              push esi             ; netobj
10002514  e8 47 26 00 00  call 10004b60        ; 4b60(netobj, target, &local, 4)
10002519  83 c4 10        add  esp,0x10
```

`4c80` 是 cdecl 1 參、裸 `ret`，所以它不清那兩格；`add esp,4` 丟掉一格後，另一格正好
成為 `4b60` 的第 3 參（buf），而第 4 參（len）是再上面一格。**這是編譯器把同一組
buf/len 棧槽重複用於兩個呼叫**（P34 `p34_wire.py` 檔頭早就記過這件事），不是新 ABI。
`0x100024b2` 同型。

## 3. 交叉驗證（同一 ABI 的實機成功）

| 來源 | 形狀 | 結果 |
|---|---|---|
| P34 probe（獨立進程） | `4c80(netobj)`、`4b60(netobj,target,buf,8)` | run-162501：主機摘席、自回聲 rc=11 |
| P51 影子 agent（SANPK 進程內） | 同上（`p51_shadow_agent_build.py` L79-91） | 2026-10-18 藏身成功：SHG2 rc=1、主機同步名單摘除、DLL 成員行保留 |
| P61 agent（SANPK 進程內） | 同上（`p61_d8_build.py` L51-61） | rc=1、tx+1，但無效果 |

三者的呼叫形狀逐字一致 ⇒ **P61 的 agent 送出的不是「非法 D8」**。

## 4. P61 負結果的正確解讀

- 00:03 那輪 `one_click_test.sh` 結束時 `one_click_state.json` 已是 `done/ok`、主機名冊=2
  ⇒ 00:45–00:55 的三發全部發生在 **幽靈已藏身、局已在 193 年** 之後。
- **自我 D8**：主機應用層已經沒有風夜的行，`3fd0` 的 type2/31d0 沒有對象可摘 ⇒ 沒有可見效果
  是預期，不能當成通道失敗。
- **踢風雲**：`3fd0` 靜態上不檢查發送者（只比 departing 與 row0.id），理論上該生效；
  但當時沒有任何主機側觀測，所以「幀沒到」與「到了被忽略」無法區分。
- 回執缺三個關鍵欄位：`4c80` 回傳的 target、own id、is_host/rowcount。因此連「target 是不是 0」
  都不知道。

## 5. 未解的問題（本輪要驗）

1. 藏身（非在席）時 `4c80(netobj)` 回什麼？若 rowcount≤1 會回 **0**，`4b60` 就是對 id 0 發。
2. 主機收不收「非在席成員」送來的 D8？
3. 在席時踢別人（departing≠own）到底生不生效？

## 6. 實驗矩陣（E1 先做，破壞性逐次報批）

| # | 狀態 | departing | 觀測 | 破壞性 |
|---|---|---|---|---|
| E1 | 在席（開局前） | 自己 | 主機 L 表 row 消失＝藏身（已知會成功）＋回執 target 應=主機 id | 否 |
| E2 | 已藏身 | 自己 | 主機 L 表無變化、無新文字 | 否 |
| E3 | 在席 | 風雲 | 主機 L 表少一行、風雲被踢、退出文字 | **是（已報批）** |
| E4 | 已藏身 | 風雲（先讓風雲重新進房） | 區分「非在席發送者能否踢人」 | **是（已報批）** |
| E5 | 已藏身 | —（正常關閉幽靈客戶端） | 主機聊天/名冊是否出現任何文字 | 否 |

## 7. 本輪工具變更

- `research/client/protocol-lab/p62_netobj_probe.py`（新，唯讀）：從幽靈 SANPK 進程讀
  `netobj+0x148/+0x43b8/+0x43bc/+0x84A8` 與 row0/row1 id，照 `4c80` 邏輯算出 target。
- `~/sgi-fengye-lab/shadow/one_click_test.sh` 加 `--no-hide`（預設行為不變，備份
  `.bak-20261020-0745`）：跑到「風夜已進房、尚未摘席」就停，供 E3 在席踢人。

## 8. 紅線

- 踢人只在自測局、每發一次報批；不踢房主；不改遊戲 EXE/存檔；不重啟幽靈客戶端（大廳留痕）。
