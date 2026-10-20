# 風夜「上身代下指令／收私聊」實測與下一步（0.2.38，2026-10-20）

## 1. 這一輪到底測了什麼

### 1.1 背景

- 主機：丁滿（本機，member id `167872591`，勢力 3 齊）
- 玩家：風雲（本機，member id `167955232`，勢力 18 巴）
- 風夜：藏身（D8）旁聽，member id `183165165`，`my_slot=5`，**不在主機 sync roster**
  （host `+84c8=2`，只有丁滿/風雲）
- 主機金 37,233；`production_buildings=186`

### 1.2 第一發：P57 frame sender spoof（broadcast）

```
agent_spoof.bin, --spoof-id 167872591
payload: 54B CSanInetDomesticCmd（actor=3、build=8、city=49、2000 金）
receipt: magic=39474853 rc=1 own=183165165 target=167872591 len=54
```

結果：主機金仍 **37,233**、186 棟、目標格無建物 → **未套用**。

### 1.3 第二發：agent_uplink + spoof（to host）

```
agent_uplink.bin, --spoof-id 167872591
receipt: magic=37474853 rc=1 own=183165165 target=167872591 len=54
```

結果：同樣未扣金、無建物。

### 1.4 第三發：host member 表 patch

- 掃 host 進程，風夜 id `183165165` 共 16 處。
- 把 `0x2702210`、`0x2701ed0` 兩處成員 id 改成 `167872591`（readback 成功）。
- 再從風夜送 p60 指令（`rc=1, phase=3, f14=3, f18=8, f1c=49, f20=2000`）。
- 主機仍未扣金／無建物。
- **已把兩處寫回 `0xaeae0ed`（readback 確認）**，host 狀態恢復。

### 1.5 判定

主機的 domestic 指令 gate 不只看 frame sender／member id，還看：

1. **DLL sync roster**（`netobj+0x84c4/+0x84c8`）——風夜不在（D8 已摘除）；
2. **應用層席位行**——風夜沒有行（D8 已摘除）。

藏身風夜只有 DLL 成員身分，兩道都沒有；因此任何 frame sender／member id 冒用都不會被
套用。`风云: hi` 在風夜 session 68 幀中 0 幀，也是同一個 gate（host 依 member/session 投遞）。
**結論：0.2.37 的「風夜只要有行就能送」只對『有席位行且同步參與』的風夜成立；藏身 D8
的風夜不可能用現有 frame 冒用完成指令／私聊。**

## 2. 0.2.38 面板行為

- 風夜**藏身**（`local.force_id = None`）→ 新指令一律拒絕，提示「風夜目前沒有勢力」。
- 風夜**已入座**（有 force）→ 允許選任何勢力；`_run_batch` 會把風夜本地席位切到目標
  slot、送 actor、再切回；`sender_label='風夜（借目標席位）'`。
- 這樣下一局以 no-hide 入座＋同步參與後，可直接從面板選丁滿/風雲測試，不需要丁滿/風雲
  的本機 client。

## 3. 下一局的正確程序（風夜-only）

1. 結束目前這局（主機 丁滿 回房間）。
2. 在同一個房間，用 **no-hide** 重新武裝風夜：
   ```
   bash ~/sgi-fengye-lab/shadow/one_click_test.sh --no-hide
   ```
   風夜會以偽名（待秋至/小白）留在席位，**不 D8**；玩家列表會看到這個偽名。
3. 主機按「開始」；風夜會收到 cmd7、拿到自己的勢力（app 行可見）。
4. 讓風夜參與 DLL 同步（P33 的 StartSync/GetCmd/EndSync 最小 worker）：host 的
   `+84c8` 會變成 3，風夜在 sync roster 裡；不參與的話主機會在回合邊界等它。
5. 在 Hub「外部指令」選丁滿或風雲的勢力下單；風夜會借目標 slot 送 actor。
6. 驗收：主機金扣 2000、目標格出現建物（陷阱在結算時出現）；若失敗，先看 host 的
   `+84c8` 是否含風夜、app 行是否還在。

## 4. 私聊／他人聊天

- 風夜入座後，**投給風夜那行的聊天**會到；投給丁滿/風雲的私聊仍不會（host 依
  member/session 投遞）。
- 要拿別人的私聊，只剩 **session-level 接管**：風夜用目標的 session id/virtual IP 進
  relay（目標先離線），讓 host 的 member 表把風夜視為目標。這需要改 relay/loader 的
  session 註冊，尚未實作；不能再靠 frame sender spoof（本輪已證 negative）。

## 5. 本輪檔案／狀態

- Hub 原始碼：`command_panel.py`（seated-any-force、hidden-refuse）、`command_service.py`
  （local force 讀取、spoof 測試未改服務路徑）。
- 測試：`python3.14 -m unittest discover -s tests` **299/299**。
- lab 證據：`p60_test_spoof.bin`、`up_spoof.bin`、`shadow_uplink_receipt.bin`、
  `inject-state-spoof1.json`、`inject-state-upspoof.json`。
- host member patch 已還原；目前遊戲仍在夏季內政，風夜仍藏身，Hub 0.2.38。
- 未完成：session-level 接管、私聊攔截、no-hide 新局實測（需主機按開始）。
