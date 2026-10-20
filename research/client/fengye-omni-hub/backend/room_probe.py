"""Owned Wine session: lobby SearchSession, explicit Open/ExitSession.

No game-process access, command injection, battle participation or automatic
ready replies. Uses an owned notification HWND and releases every packet.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target')
    ap.add_argument('--session-name')
    ap.add_argument('--username')
    ap.add_argument('--hold', type=int, default=86400)
    ap.add_argument('--session-dir', required=True)
    ap.add_argument('--lab', required=True)
    args = ap.parse_args()
    folder = Path(args.session_dir)
    sys.path.insert(0, args.lab)
    sys.path.insert(0, str(folder))
    from p28_window import Receiver, WM_EVENT, WM_DATA, WM_CHAT
    from room_protocol import request, reserve_join
    # 開局前流程（cmd2 無特徵註冊／D8 自身離場）沿用研究鏈已驗證模組；
    # 拾取失敗時僅停用這兩步，大廳與進退房不受影響。
    try:
        from p32_protocol import cmd2 as build_cmd2
        from p33_wire import inspect_inner, own_sync_withdrawal as build_d8_body
        from p34_wire import RVA_GET_HOST_OR_SELF, RVA_RELIABLE_SEND
        from p20_cmd2_verified_probe import KOEINM as EXPECT_KOEINM
        prestart_available = True
    except Exception:
        build_cmd2 = build_d8_body = inspect_inner = None
        RVA_GET_HOST_OR_SELF = RVA_RELIABLE_SEND = EXPECT_KOEINM = None
        prestart_available = False
    if c.sizeof(c.c_void_p) != 4:
        raise ValueError('32-bit native runtime required')
    def read(name):
        try:
            return json.loads((folder / name).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
    def write(name, data):
        path = folder / name
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        tmp.replace(path)
    audit = (folder / 'packets.jsonl').open('a', encoding='utf-8', buffering=1)
    state = {'phase': 'starting', 'connected': False, 'application_ready': False,
             'room_query': {}, 'channel': {}, 'last_result': None}
    own = None
    def log(event):
        # 2026-10-17：移除 host_init_wait 判定——正常進房時主機一定會先發一次
        # CSanInetInitGameData（run-174654 實證），該訊號無法區分「開始被提前按」，
        # 會誤擋每一次 D8。藏身改回只依「開局前狀態＝1」＋目標核對。
        event.update(wall=time.time())
        if (state.get('ghost_withdrawn') and not state.get('exit_seen_wall')
                and event.get('ev') == 'received_packet'):
            obj = event.get('object') or {}
            if obj.get('cmd') == 1 and 0 < (event.get('length') or 0) <= 40:
                # 主機處理完藏身的回證：退場物件（cmd1/36B）回到本端。
                state['exit_seen_wall'] = event['wall']
        audit.write(json.dumps(event, ensure_ascii=False) + '\n')
    root = Path(r'C:\sgi\run-3.5')
    dllpath = root / '3I/Koeinm.dll'
    hookpath = root / 'NetHookCore.dll'
    # Bind the installed binaries in the run, rather than guessing version
    # offsets. Only public DLL exports are used by this viewer.
    state['binary_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (dllpath, hookpath)}
    if state['binary_sha256']['NetHookCore.dll'] != '5b3790982f7c54f891e5b3c8559e7a61c7589d8a4a9d68bc9f8f8992b5b678b4':
        raise ValueError('unexpected transport binary')
    dll = c.WinDLL(str(dllpath))
    hook = c.WinDLL(str(hookpath))
    def export(name, params, result=c.c_int):
        f = getattr(dll, '_NetMsg_' + name)
        f.argtypes, f.restype = params, result
        return f
    start = export('Start@36', [c.c_uint32]*8+[c.POINTER(c.c_uint32)])
    search = export('SearchSession@12', [c.c_char_p, w.HWND, w.UINT])
    getip = export('GetIPAddress@4', [c.POINTER(c.c_void_p)])
    opens = export('OpenSession@20', [c.c_char_p]*3+[c.c_uint32]*2)
    hostid = export('GetHostID@0', [], c.c_uint32)
    setdata = export('SetDataWindow@8', [w.HWND, w.UINT])
    setchat = export('SetChatWindow@8', [w.HWND, w.UINT])
    decode = export('DecodeWParam@4', [c.c_uint32])
    delete = export('DeletePacket@4', [c.c_void_p])
    accept = export('AcceptEXIT@4', [c.c_uint32])
    connected = export('IsConnected@0', [])
    exits = export('ExitSession@0', [])
    end = export('End@0', [])
    send_data = export('SendData@8', [c.c_char_p, c.c_int])
    receiver = Receiver(log, decode, delete, accept)
    u, k = receiver.u, receiver.k
    k.GlobalFree.argtypes, k.GlobalFree.restype = [c.c_void_p], c.c_void_p
    k.GetComputerNameA.argtypes, k.GetComputerNameA.restype = [c.c_char_p, c.POINTER(w.DWORD)], w.BOOL
    k.GetModuleHandleW.argtypes, k.GetModuleHandleW.restype = [w.LPCWSTR], c.c_void_p
    room_msg = 0x2403
    started = joined = False
    seen = set()
    next_search, next_save = 0, 0
    prestart_handles = {}
    slot_netobj = None
    last_slot_key = None

    def rd32(addr):
        return int(c.c_uint32.from_address(addr).value)

    def prestart_netobj():
        base = k.GetModuleHandleW('Koeinm.dll')
        addr = int(base) if base is not None else 0
        if not addr:
            raise ValueError('Koeinm.dll 未載入')
        return addr + 0x12170

    def prestart_calls():
        if 'get_or_self' not in prestart_handles:
            if not prestart_available:
                raise ValueError('可靠提交模組不可用')
            base = k.GetModuleHandleW('Koeinm.dll')
            addr = int(base) if base is not None else 0
            if not addr:
                raise ValueError('Koeinm.dll 未載入')
            prestart_handles['get_or_self'] = c.CFUNCTYPE(c.c_int, c.c_void_p)(
                addr + RVA_GET_HOST_OR_SELF)
            prestart_handles['reliable_submit'] = c.CFUNCTYPE(
                c.c_int, c.c_void_p, c.c_uint32, c.c_char_p, c.c_int)(addr + RVA_RELIABLE_SEND)
        return prestart_handles['get_or_self'], prestart_handles['reliable_submit']
    def do_search():
        nonlocal next_search
        # Search returns thread messages, so drain them BEFORE generic pump.
        rc = int(search(b'255.255.255.255', None, room_msg))
        msg = w.MSG()
        rooms = {}
        while u.PeekMessageW(c.byref(msg), None, room_msg, room_msg, 1):
            if msg.wParam == 5 and msg.lParam:
                ptr = c.c_void_p(msg.lParam)
                try:
                    raw = c.string_at(ptr, 80)
                    row = {'id': str(struct.unpack_from('<I', raw)[0]),
                           'name': raw[4:35].split(b'\0')[0].decode('gbk', 'replace'),
                           'host': raw[35:66].split(b'\0')[0].decode('gbk', 'replace'),
                           'maximum': struct.unpack_from('<I', raw, 68)[0],
                           'current': struct.unpack_from('<I', raw, 72)[0]}
                    row['virtual_ip'] = '.'.join(str(v) for v in struct.pack('!I', int(row['id'])))
                    rooms[row['id']] = row
                finally:
                    k.GlobalFree(ptr)
        now = time.time()
        if rc == 0:
            state['room_query'] = {'observed_at': now, 'rooms': list(rooms.values()),
                'status': 'replies_received' if rooms else 'unconfirmed_empty', 'rc': rc,
                'source': 'SearchSession through owned relay'}
        else:
            state['room_query'] = dict(state['room_query'], error='SearchSession rc=' + str(rc))
        next_search = time.monotonic() + 15
        return rc

    def perform_register():
        """cmd2 一次（seq0 免檢）；條件不符時 raise，由呼叫端轉為 error。"""
        if not prestart_available:
            raise ValueError('報到模組不可用（採集端缺少指令模組）')
        if not (joined and connected()):
            raise ValueError('還沒進房，無法報到')
        if state.get('ghost_registered'):
            raise ValueError('這局已報到過（只做一次），不重送')
        if state['binary_sha256']['Koeinm.dll'] != EXPECT_KOEINM:
            raise ValueError('程式版本不符，未執行')
        machine_buffer = c.create_string_buffer(256)
        machine_size = w.DWORD(256)
        if not k.GetComputerNameA(machine_buffer, c.byref(machine_size)):
            raise c.WinError()
        machine = machine_buffer.raw[:machine_size.value]
        machine_text = machine.decode('gbk', 'replace')
        cmd2_blob = build_cmd2(machine)
        netobj_now = prestart_netobj()
        # 2026-10-17：帶序號註冊＋等主機確認（+8440 為 ACK 序號推進）。新成員的
        # 第一幀應帶主機門口期望的下一號（新行 sB=0 → 1）；逐號重試（1→2→3），
        # 被門口拒收的嘗試無副作用。確認後離場訊號才走快線（run-174654 實證：
        # cmd2 被確認後 D8 數十毫秒內送達）；未確認則回退 seq0 免檢（主機必收
        # 但無 ACK，離場訊號可能慢約 2 分鐘）。
        rc, acked, used_ctr = 0, False, None
        for seq in (1, 2, 3):
            c.c_uint32.from_address(netobj_now + 0x8440).value = seq
            log({'ev': 'register_enter', 'machine_name': machine_text, 'ctr_set': seq,
                 'raw_hex': cmd2_blob.hex(), 'sha256': hashlib.sha256(cmd2_blob).hexdigest()})
            rc = int(send_data(cmd2_blob, len(cmd2_blob)))
            if rc != 0:
                break
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                receiver.pump()
                time.sleep(0.02)
                if rd32(netobj_now + 0x8440) > seq:
                    acked = True
                    break
            if acked:
                used_ctr = seq
                break
        if rc == 0 and not acked:
            c.c_uint32.from_address(netobj_now + 0x8440).value = 0
            log({'ev': 'register_enter', 'machine_name': machine_text, 'ctr_set': 0,
                 'fallback': True, 'raw_hex': cmd2_blob.hex(),
                 'sha256': hashlib.sha256(cmd2_blob).hexdigest()})
            rc = int(send_data(cmd2_blob, len(cmd2_blob)))
        receipt = {'wall': time.time(), 'rc': rc, 'machine_name': machine_text,
                   'sha256': hashlib.sha256(cmd2_blob).hexdigest(),
                   'ctr_set': used_ctr if acked else (0 if rc == 0 else None), 'acked': acked}
        state['ghost_registered'] = True
        state['register'] = receipt
        write('state.json', state)
        log({'ev': 'register_return', 'rc': rc, 'acked': acked, 'ctr_set': receipt['ctr_set']})
        return rc, receipt

    def perform_d8():
        """D8 一次（可靠通道）；開局等待鎖住時拒發（安全機制）。"""
        if not prestart_available:
            raise ValueError('藏身模組不可用（採集端缺少指令模組）')
        if not (joined and connected()):
            raise ValueError('還沒進房，無法藏身')
        if not state.get('ghost_registered'):
            raise ValueError('要先報到才能藏身')
        if state.get('ghost_withdrawn'):
            raise ValueError('這局已藏身過（只做一次），不重送')
        if state['binary_sha256']['Koeinm.dll'] != EXPECT_KOEINM:
            raise ValueError('程式版本不符，未執行')
        netobj_now = prestart_netobj()
        state_now = rd32(netobj_now + 0x84a8)
        if state_now != 1:
            raise ValueError('目前不是開局前（狀態 %s），未執行' % state_now)
        # 2026-10-16 熱修：seq0 免檢通道不會推進 +8440，ACK 條件永遠不成立而
        # 鎖死摘席。依 run-174654 實證（cmd2→即刻 D8 成功），摘席前置維持
        # 「已註冊＋state=1」即可，不再等 ACK。
        body = build_d8_body(own)
        buf = c.create_string_buffer(body, len(body))
        get_or_self_call, reliable_call = prestart_calls()
        target = int(get_or_self_call(netobj_now))
        if target != int(hostid()):
            raise ValueError('連線目標不符，未執行')
        log({'ev': 'd8_enter', 'body_hex': body.hex(),
             'sha256': hashlib.sha256(body).hexdigest(), 'target': target,
             'native_state_before': state_now})
        stamp = rd32(netobj_now + 0x8440)
        state['ghost_withdrawn'] = True   # 已送出（一次性）；以下僅補確認回執
        raw_rc = int(reliable_call(netobj_now, target, buf, len(body)))
        # 2026-10-17：等主機確認——+8440 序號推進（ACK）或退場回證（cmd1/36B）。
        # 快線數十毫秒；seq0 免檢回退路徑無 ACK，等不到時記 fast=false
        #（主機處理可能約 2 分鐘——介面會提示等名單消失再按開始）。
        fast = False
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            receiver.pump()
            time.sleep(0.02)
            if rd32(netobj_now + 0x8440) > stamp or state.get('exit_seen_wall'):
                fast = True
                break
        receipt = {'wall': time.time(), 'raw_rc': raw_rc, 'target': target,
                   'sha256': hashlib.sha256(body).hexdigest(), 'fast': fast}
        state['d8'] = receipt
        write('state.json', state)
        log({'ev': 'd8_return', 'raw_rc': raw_rc, 'target': target, 'fast': fast})
        return raw_rc, receipt
    try:
        flag = c.c_uint32()
        rc = int(start(8, 64, 7777, int(receiver.hwnd), WM_EVENT, 78731, 0, 0, c.byref(flag)))
        started = rc == 0
        if not started:
            raise RuntimeError('NetMsg_Start rc=' + str(rc))
        setdata(receiver.hwnd, WM_DATA)
        setchat(receiver.hwnd, WM_CHAT)
        ptr = c.c_void_p()
        count = int(getip(c.byref(ptr)))
        if not 0 < count <= 32 or not ptr.value:
            raise RuntimeError('no registered relay address')
        own = c.c_uint32.from_address(ptr.value).value
        state.update(phase='lobby', channel={'own_id': own, 'local_game_port': 7777,
                     'app_id': 78731, 'transport': 'NetHookCore/Koeinm', 'hwnd': int(receiver.hwnd)})
        deadline = time.monotonic() + min(args.hold, 86400)
        while time.monotonic() < deadline:
            if time.time() - (folder / 'heartbeat').stat().st_mtime > 300:
                # 2026-10-17 深夜：90→300 秒。長局實測兩次因觀眾端短暫停頓
                #（SSH/輪詢打嗝）被誤殺；放寬到 5 分鐘，真斷開仍會正常收尾。
                log({'ev': 'viewer_heartbeat_expired'})
                break
            command = read('request.json')
            if command.get('id') and command['id'] not in seen:
                # Persist reservation BEFORE native calls; never replay after
                # failure, crash, lost SSH reply or process restart.
                seen.add(command['id'])
                write('reserved.json', {'ids': sorted(seen)})
                result = {'id': command['id'], 'op': command.get('op'), 'wall': time.time()}
                stop = False
                try:
                    payload = request(command)
                    if command.get('session_id') != read('identity.json').get('session_id'):
                        raise ValueError('會話識別不符')
                    if not isinstance(command.get('wall'), (float, int)) or not 0 <= time.time()-command['wall'] <= 30:
                        raise ValueError('操作已過期')
                    if payload['op'] == 'join':
                        payload = reserve_join(payload, state)
                        state['phase'] = 'joining'
                        state['observed_at'] = time.time()
                        write('state.json', state)
                        log({'ev': 'open_session_enter', 'room_id': payload['room_id'], 'nickname': payload['nickname']})
                        rc = int(opens(payload['virtual_ip'].encode('ascii'), payload['session_name'].encode('gbk'),
                                       payload['nickname'].encode('gbk'), own, 3000))
                        joined = rc == 0
                        is_connected = bool(connected())
                        state.update(phase='room' if joined and is_connected else 'lobby', connected=is_connected,
                                     nickname=payload['nickname'], selected_room=payload if joined else None)
                        state['channel'].update(host_id=int(hostid()) if joined else None,
                                                target_virtual_ip=payload['virtual_ip'] if joined else None,
                                                open_rc=rc)
                        if joined and is_connected:
                            # 2026-10-16 熱修：新一輪入座＝新成員週期，重設一次性旗標，
                            # 否則同一會話「退出→改名→再進」會被舊旗標擋住，行不會補名。
                            state.update(ghost_registered=False, ghost_withdrawn=False,
                                         register=None, d8=None, register_ack=False)
                        result.update(rc=rc, status='completed' if joined and is_connected else 'failed',
                                      detail='已進房（連線成功）' if joined and is_connected else '房間沒有接受連接')
                        if joined and is_connected and payload.get('quick'):
                            # 2026-10-17：一鍵鏈——cmd2 與 D8 緊接在同一操作內完成，
                            # 縮短席位可見窗口；D8 前先泵訊息，讓主機的開局等待
                            # （若已有人按開始）能即時進入安全檢查。
                            try:
                                reg_rc, _reg = perform_register()
                                d8_rc, _d8rec = perform_d8()
                                result.update(rc=0, status='completed', detail=(
                                    '報到完成 → 藏身完成（主機已確認）'
                                    if _d8rec.get('fast')
                                    else '報到完成 → 藏身已送出（等主機處理，約 2 分鐘）'))
                            except Exception as error:
                                result.update(rc=0, status='error',
                                              error='自動準備沒完成：' + str(error)[:180])
                    elif payload['op'] in ('leave', 'stop'):
                        rc = int(exits()) if joined or connected() else None
                        is_connected = bool(connected())
                        joined = is_connected
                        state.update(phase='room' if is_connected else 'lobby', connected=is_connected)
                        if not is_connected:
                            state['selected_room'] = None
                            state['channel'].update(host_id=None, target_virtual_ip=None, open_rc=None)
                        # ExitSession/End use BOOL-like returns (historical
                        # normal cleanup rc=1); verify actual local connection.
                        result.update(rc=rc, status='unknown' if is_connected else 'completed',
                                      detail='已離開房間（房主端顯示為準）' if not is_connected else '仍顯示連線中，已停止重試')
                        stop = payload['op'] == 'stop' and not is_connected
                    elif payload['op'] == 'search':
                        rc = do_search()
                        result.update(rc=rc, status='completed' if rc == 0 else 'failed')
                    elif payload['op'] == 'register':
                        rc, _receipt = perform_register()
                        result.update(rc=rc, status='completed' if rc == 0 else 'failed',
                                      detail=('已報到（主機已確認）' if _receipt.get('acked')
                                              else '已報到（已送出）')
                                      if rc == 0 else '報到呼叫未成功')
                    elif payload['op'] == 'd8':
                        raw_rc, _receipt = perform_d8()
                        if raw_rc > 0:
                            detail = ('已藏身（主機已確認）；連線保持，可持續旁聽'
                                      if _receipt.get('fast')
                                      else '藏身已送出——主機處理約需 2 分鐘；等名單上風夜消失再按開始')
                        else:
                            detail = '藏身呼叫未成功'
                        result.update(rc=raw_rc, status='completed' if raw_rc > 0 else 'failed',
                                      detail=detail)
                    else:
                        raise ValueError('此操作不可傳給探針')
                except Exception as error:
                    result.update(status='error', error=str(error)[:200])
                state['last_result'] = result
                write('result.json', result)
                log(dict(result, ev='room_control_result'))
                if stop:
                    break
            if not joined and time.monotonic() >= next_search:
                do_search()
            receiver.pump()
            if prestart_available:
                # 2026-10-17：接收槽取樣（移植自 P43 探針；只讀本進程自己
                # 的 DLL 槽，記錄 control3/control5 幀變化，供指令解讀）。
                if slot_netobj is None:
                    try:
                        slot_netobj = prestart_netobj()
                    except ValueError:
                        slot_netobj = None
                if slot_netobj:
                    try:
                        slot_size = c.c_int32.from_address(slot_netobj + 0x414c).value
                        if 0 < slot_size <= 0x4000:
                            slot_sender = rd32(slot_netobj + 0x4150)
                            raw_slot = c.string_at(slot_netobj + 0x14c, slot_size)
                            key = (slot_sender, raw_slot)
                            if key != last_slot_key and raw_slot[0] == 0x63:
                                last_slot_key = key
                                try:
                                    parsed_slot = inspect_inner(raw_slot)
                                except ValueError:
                                    parsed_slot = {'unknown_control_or_incomplete_slot': True}
                                log({'ev': 'native_slot_observed', 'sender_slot': slot_sender,
                                     'length': slot_size, 'raw_hex': raw_slot.hex(),
                                     'sha256': hashlib.sha256(raw_slot).hexdigest(),
                                     'inner': parsed_slot,
                                     'evidence_type': 'sampled_owned_receive_slot; possible_missed_frames'})
                    except (ValueError, OSError):
                        pass
            is_connected = bool(connected())
            if joined and not is_connected:
                joined = False
                state.update(phase='disconnected', connected=False)
            if time.monotonic() >= next_save:
                state.update(observed_at=time.time(), connected=is_connected,
                             received=receiver.count, released=receiver.freed, receiver_errors=receiver.errors)
                if started and prestart_available:
                    try:
                        netobj_sample = prestart_netobj()
                        state['native_sync_state'] = rd32(netobj_sample + 0x84a8)
                        state['native_tx_seq'] = rd32(netobj_sample + 0x8440)
                        if state.get('ghost_registered'):
                            state['register_ack'] = bool(state.get('register_ack')
                                                         or state['native_tx_seq'] > 0)
                    except (ValueError, OSError):
                        pass
                write('state.json', state)
                next_save = time.monotonic() + 1
            time.sleep(.05)
    except Exception as error:
        state.update(error=type(error).__name__ + ': ' + str(error)[:200])
        log({'ev': 'session_error', 'error': state['error']})
    finally:
        if joined or started and connected():
            state['exit_rc'] = int(exits())
        if started:
            state['end_rc'] = int(end())
        receiver.close()
        state.update(phase='stopped', connected=False, observed_at=time.time())
        write('state.json', state)
        audit.close()


if __name__ == '__main__':
    main()
